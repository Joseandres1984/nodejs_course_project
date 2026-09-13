from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple
from zoneinfo import ZoneInfo

import commercial_execution
from autonomy_governor import record_decision


VERSION = "1.0"
PUBLIC_BASE_URL = (os.getenv("LUMEN_PUBLIC_BASE_URL") or "https://lumen-web-production-5755.up.railway.app").strip().rstrip("/")
LIVE = os.getenv("LUMEN_OUTBOUND_LIVE", "false").lower() == "true"
MAX_NEW_PER_CYCLE = max(0, min(3, int(os.getenv("LUMEN_OUTBOUND_MAX_NEW_PER_CYCLE", "1"))))
MAX_NEW_PER_DAY = max(0, min(12, int(os.getenv("LUMEN_OUTBOUND_MAX_NEW_PER_DAY", "3"))))
MAX_FOLLOWUPS_PER_CYCLE = max(0, min(2, int(os.getenv("LUMEN_OUTBOUND_MAX_FOLLOWUPS_PER_CYCLE", "1"))))
MIN_SCORE = max(0.0, min(100.0, float(os.getenv("LUMEN_OUTBOUND_MIN_ACCOUNT_SCORE", "55"))))
RECONTACT_DAYS = max(7, min(180, int(os.getenv("LUMEN_OUTBOUND_RECONTACT_DAYS", "30"))))
MAX_DELIVERY_CHECKS = max(0, min(10, int(os.getenv("LUMEN_OUTBOUND_DELIVERY_CHECKS_PER_CYCLE", "3"))))
MAX_SEND_RETRIES = max(0, min(3, int(os.getenv("LUMEN_OUTBOUND_SEND_RETRIES", "2"))))
RESEND_API_KEY = os.getenv("LUMEN_RESEND_API_KEY", "").strip()
AR_TZ = ZoneInfo("America/Argentina/Buenos_Aires")
FREE_DOMAINS = {"gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "icloud.com", "live.com", "proton.me", "protonmail.com"}

_ORIGINAL_COMMERCIAL_EXECUTION = commercial_execution.commercial_execution_tick


def utcnow_dt() -> datetime:
    return datetime.now(timezone.utc)


def utcnow() -> str:
    return utcnow_dt().strftime("%Y-%m-%d %H:%M:%S UTC")


def local_day() -> str:
    return utcnow_dt().astimezone(AR_TZ).date().isoformat()


def _parse(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S UTC", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _email_domain(email: str) -> str:
    value = str(email or "").strip().lower()
    if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", value):
        return ""
    return value.rsplit("@", 1)[-1].removeprefix("www.")


def _company(account: Dict[str, Any]) -> str:
    return " ".join(str(account.get("company_name") or account.get("name_hint") or account.get("site_title") or account.get("domain") or "empresa").split())[:160]


def _category(account: Dict[str, Any]) -> str:
    return " ".join(str(account.get("category") or "soluciones B2B").split())[:160]


def _risk_allows(state: Dict[str, Any], account: Dict[str, Any]) -> bool:
    risk = dict((state.get("counterparty_risk_index", {}) or {}).get(str(account.get("id") or ""), {}) or {})
    return risk.get("risk_tier") != "BLOCKED" and risk.get("can_outreach") is not False


def _relationship(state: Dict[str, Any], account: Dict[str, Any], email: str) -> Dict[str, Any]:
    aid = str(account.get("id") or "")
    for row in state.get("commercial_relationships", []) or []:
        if aid and str(row.get("account_id") or "") == aid:
            return row
        if email and str(row.get("commercial_email") or "").strip().lower() == email:
            return row
    return {}


def _suppressed(state: Dict[str, Any], email: str) -> bool:
    target = email.strip().lower()
    if target in {str(x).strip().lower() for x in state.get("opt_out", []) or []}:
        return True
    for row in state.get("email_suppression", []) or []:
        if isinstance(row, dict) and str(row.get("email") or "").strip().lower() == target:
            return True
        if isinstance(row, str) and row.strip().lower() == target:
            return True
    return False


def _professional_case(state: Dict[str, Any], account_id: str) -> bool:
    for case in state.get("professional_cases", []) or []:
        if str(case.get("account_id") or case.get("counterparty_account_id") or "") == account_id:
            return True
    return False


def _score(state: Dict[str, Any], account: Dict[str, Any]) -> Tuple[float, List[str]]:
    score = 0.0
    reasons: List[str] = []
    if account.get("verified_company"):
        score += 15; reasons.append("empresa verificada")
    if account.get("verified_contact") and account.get("commercial_email"):
        score += 15; reasons.append("email corporativo verificado")
    try:
        score += min(15.0, max(0.0, float(account.get("verification_score") or 0)) * 0.15)
    except Exception:
        pass
    try:
        score += min(10.0, max(0.0, float(account.get("lead_score") or 0)) * 0.10)
    except Exception:
        pass
    if account.get("category"):
        score += 5; reasons.append("categoría identificada")
    if account.get("direct_inbound_demand"):
        score += 30; reasons.append("demanda entrante directa")
    elif account.get("demand_signal"):
        score += 20; reasons.append("señal de demanda")
    if str(account.get("type") or "") == "supplier":
        score += 10; reasons.append("proveedor apto para red B2B")
    if _professional_case(state, str(account.get("id") or "")):
        score += 5; reasons.append("expediente Deep Work")
    return round(min(100.0, score), 1), reasons


def _recently_contacted(state: Dict[str, Any], email: str) -> bool:
    cutoff = utcnow_dt() - timedelta(days=RECONTACT_DAYS)
    for item in reversed(state.get("outbox", []) or []):
        if str(item.get("contact") or "").strip().lower() != email:
            continue
        if item.get("source") not in {"outbound_engine", "distribution_operator_canary"}:
            continue
        when = _parse(item.get("sent_at") or item.get("created_at"))
        if when and when >= cutoff and item.get("status") not in {"blocked", "blocked_quality"}:
            return True
    return False


def _eligible(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    prospects: List[Dict[str, Any]] = []
    for account in state.get("candidate_accounts", []) or []:
        if str(account.get("type") or "") not in {"buyer", "supplier"}:
            continue
        if not account.get("verified_company") or not account.get("verified_contact"):
            continue
        email = str(account.get("commercial_email") or "").strip().lower()
        domain = _email_domain(email)
        official = str(account.get("domain") or "").strip().lower().removeprefix("www.")
        if not domain or domain in FREE_DOMAINS:
            continue
        if official and domain != official and not domain.endswith("." + official):
            continue
        if str(account.get("contact_policy") or "public_corporate_channels_only") != "public_corporate_channels_only":
            continue
        if _suppressed(state, email) or not _risk_allows(state, account):
            continue
        relation = _relationship(state, account, email)
        if relation.get("opted_out") or relation.get("relationship_state") in {"do_not_contact", "cooldown"}:
            continue
        if _recently_contacted(state, email):
            continue
        score, reasons = _score(state, account)
        if score < MIN_SCORE:
            continue
        prospects.append({"account": account, "score": score, "reasons": reasons, "email": email})
    prospects.sort(key=lambda x: (-float(x["score"]), 0 if x["account"].get("direct_inbound_demand") else 1, str(x["account"].get("id") or "")))
    return prospects


def _campaign_variant(state: Dict[str, Any], audience: str, account_id: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    campaign = next((x for x in state.get("acquisition_campaigns", []) or [] if x.get("status") == "active" and x.get("audience") == audience), {})
    variants = list(campaign.get("variants", []) or [])
    if not variants:
        return campaign, {}
    digest = int(hashlib.sha1((account_id + "|outbound-v1").encode("utf-8")).hexdigest()[:8], 16)
    # Deterministic exploration keeps A/B/C measurable without random duplicate behavior.
    variant = variants[digest % len(variants)]
    return campaign, variant


def _sequence_id(account_id: str, email: str) -> str:
    return "SEQ-" + hashlib.sha1(("LUMEN-OUTBOUND|" + account_id + "|" + email).encode("utf-8")).hexdigest()[:12].upper()


def _message_text(account: Dict[str, Any], variant: Dict[str, Any], tracking_url: str) -> Tuple[str, str, str]:
    company = _company(account)
    category = _category(account)
    role = str(account.get("type") or "")
    if role == "buyer":
        if account.get("direct_inbound_demand"):
            kind = "buyer_requirement_request"
            subject = f"{company}: validación breve de necesidad B2B"
            body = (
                f"Queremos confirmar si sigue vigente la necesidad vinculada a {category}. "
                "LUMEN puede investigar alternativas y ordenar una comparación de proveedores sobre datos confirmados, sin comprometer una compra."
            )
        else:
            kind = "buyer_intro"
            subject = f"Alternativas B2B para {category}"
            body = (
                f"LUMEN ayuda a equipos de compras a investigar y comparar proveedores vinculados a {category}. "
                "Si hoy tienen una necesidad concreta, pueden compartirnos el requerimiento y trabajamos sobre evidencia verificable."
            )
    else:
        kind = "network_supplier_intro"
        subject = f"LUMEN B2B · oportunidades compatibles con {category}"
        body = (
            f"Estamos ampliando una red de proveedores B2B vinculados a {category}. "
            "LUMEN investiga necesidades y sólo acerca conversaciones cuando existe un encaje razonable; no prometemos volumen ni ventas sin evidencia."
        )
    if variant.get("body"):
        body += "\n\n" + str(variant.get("body"))[:550]
    if tracking_url:
        body += f"\n\nMás información: {tracking_url}"
    body += "\n\nSi no corresponde contactarlos por este medio, avísennos y no volveremos a escribir."
    return kind, subject[:180], body[:5000]


def _daily_new_count(state: Dict[str, Any]) -> int:
    today = local_day()
    return sum(1 for x in state.get("outbox", []) or [] if x.get("source") == "outbound_engine" and x.get("sequence_step") == 1 and x.get("outbound_local_day") == today)


def _queue_new(state: Dict[str, Any], prospects: List[Dict[str, Any]]) -> int:
    if not LIVE or MAX_NEW_PER_CYCLE <= 0:
        return 0
    remaining = max(0, MAX_NEW_PER_DAY - _daily_new_count(state))
    budget = min(MAX_NEW_PER_CYCLE, remaining)
    if budget <= 0:
        return 0
    outbox = state.setdefault("outbox", [])
    sequences = state.setdefault("outbound_sequences", [])
    sequence_ids = {str(x.get("id") or "") for x in sequences}
    queued = 0
    for prospect in prospects:
        if queued >= budget:
            break
        account = prospect["account"]
        email = prospect["email"]
        aid = str(account.get("id") or "")
        seq_id = _sequence_id(aid, email)
        if seq_id in sequence_ids:
            continue
        audience = "buyer" if account.get("type") == "buyer" else "supplier"
        campaign, variant = _campaign_variant(state, audience, aid)
        token = str(variant.get("token") or "")
        tracking_url = PUBLIC_BASE_URL + f"/c/{token}" if token else PUBLIC_BASE_URL + "/market"
        kind, subject, body = _message_text(account, variant, tracking_url)
        message_id = f"OUT-{len(outbox)+1:05d}"
        row = {
            "id": message_id,
            "kind": kind,
            "counterparty": _company(account),
            "counterparty_account_id": aid,
            "channel": "email",
            "contact": email,
            "contact_verified": True,
            "subject": subject,
            "body": body,
            "category": account.get("category"),
            "status": "ready",
            "source": "outbound_engine",
            "outbound_sequence_id": seq_id,
            "sequence_step": 1,
            "campaign_id": campaign.get("id"),
            "variant_id": variant.get("id"),
            "tracking_url": tracking_url,
            "target_score": prospect["score"],
            "target_reasons": prospect["reasons"][:8],
            "outbound_local_day": local_day(),
            "created_at": utcnow(),
        }
        outbox.append(row)
        sequences.append({
            "id": seq_id,
            "account_id": aid,
            "company": _company(account),
            "role": account.get("type"),
            "contact": email,
            "category": account.get("category"),
            "campaign_id": campaign.get("id"),
            "variant_id": variant.get("id"),
            "tracking_url": tracking_url,
            "target_score": prospect["score"],
            "status": "queued",
            "message_ids": [message_id],
            "created_at": utcnow(),
            "updated_at": utcnow(),
        })
        sequence_ids.add(seq_id)
        queued += 1
        record_decision(
            state,
            engine="Outbound Engine",
            object_type="account",
            object_id=aid,
            decision="governed_outreach_queued",
            reason=f"Prospecto corporativo verificado con score {prospect['score']}; contacto público, riesgo habilitado y sin contacto reciente.",
            action="prepare_outreach",
            confidence=min(0.99, max(0.55, float(prospect["score"]) / 100.0)),
            evidence_refs=list(account.get("commercial_contact_evidence") or [])[:5],
        )
    return queued


def _latest_engine_sent(state: Dict[str, Any], contact: str) -> Dict[str, Any]:
    rows = [x for x in state.get("outbox", []) or [] if x.get("source") == "outbound_engine" and x.get("status") == "sent" and str(x.get("contact") or "").strip().lower() == contact]
    rows.sort(key=lambda x: str(x.get("sent_at") or x.get("created_at") or ""), reverse=True)
    return rows[0] if rows else {}


def _pending_followup(state: Dict[str, Any], contact: str) -> bool:
    return any(
        x.get("source") == "outbound_engine" and x.get("kind") == "follow_up"
        and str(x.get("contact") or "").strip().lower() == contact
        and x.get("status") in {"ready", "needs_verified_contact", "send_failed"}
        for x in state.get("outbox", []) or []
    )


def _queue_followups(state: Dict[str, Any]) -> int:
    if not LIVE or MAX_FOLLOWUPS_PER_CYCLE <= 0:
        return 0
    queued = 0
    outbox = state.setdefault("outbox", [])
    seq_index = {str(x.get("id") or ""): x for x in state.setdefault("outbound_sequences", [])}
    for rel in state.get("commercial_relationships", []) or []:
        if queued >= MAX_FOLLOWUPS_PER_CYCLE:
            break
        if not rel.get("follow_up_due") or rel.get("opted_out") or rel.get("relationship_state") != "follow_up_due":
            continue
        contact = str(rel.get("commercial_email") or "").strip().lower()
        if not contact or _suppressed(state, contact) or _pending_followup(state, contact):
            continue
        source = _latest_engine_sent(state, contact)
        if not source:
            continue
        seq_id = str(source.get("outbound_sequence_id") or "")
        seq = seq_index.get(seq_id, {})
        step = min(3, int(rel.get("follow_up_count") or 0) + 2)
        msg_id = f"OUT-{len(outbox)+1:05d}"
        body = (
            "Retomamos brevemente el mensaje anterior por si quedó pendiente. "
            "Si el tema sigue vigente, podemos avanzar con una conversación concreta; si no corresponde, no hace falta responder.\n\n"
            "Si prefieren no recibir más mensajes de LUMEN, avísennos y lo respetamos de inmediato."
        )
        outbox.append({
            "id": msg_id,
            "kind": "follow_up",
            "counterparty": source.get("counterparty"),
            "counterparty_account_id": source.get("counterparty_account_id"),
            "channel": "email",
            "contact": contact,
            "contact_verified": True,
            "subject": ("Seguimiento · " + str(source.get("subject") or "LUMEN B2B"))[:180],
            "body": body,
            "category": source.get("category"),
            "status": "ready",
            "source": "outbound_engine",
            "outbound_sequence_id": seq_id,
            "sequence_step": step,
            "parent_outbox_id": source.get("id"),
            "campaign_id": source.get("campaign_id"),
            "variant_id": source.get("variant_id"),
            "tracking_url": source.get("tracking_url"),
            "outbound_local_day": local_day(),
            "created_at": utcnow(),
        })
        if seq:
            seq.setdefault("message_ids", []).append(msg_id)
            seq["status"] = "follow_up_queued"
            seq["updated_at"] = utcnow()
        queued += 1
    return queued


def _requeue_failures(state: Dict[str, Any]) -> int:
    count = 0
    for item in state.get("outbox", []) or []:
        if item.get("source") != "outbound_engine" or item.get("status") != "send_failed":
            continue
        if int(item.get("outbound_retry_count") or 0) >= MAX_SEND_RETRIES:
            continue
        item["outbound_retry_count"] = int(item.get("outbound_retry_count") or 0) + 1
        item["last_error_previous"] = item.pop("last_error", None)
        item["status"] = "ready"
        item["outbound_retry_at"] = utcnow()
        count += 1
    return count


def _resend_event(message_id: str) -> str | None:
    if not RESEND_API_KEY or not message_id:
        return None
    req = urllib.request.Request(
        f"https://api.resend.com/emails/{message_id}",
        headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read(12000).decode("utf-8", errors="replace") or "{}")
            return str(payload.get("last_event") or "").strip().lower() or None
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError):
        return None


def _check_delivery(state: Dict[str, Any]) -> int:
    checked = 0
    if MAX_DELIVERY_CHECKS <= 0 or not RESEND_API_KEY:
        return checked
    suppressions = state.setdefault("email_suppression", [])
    suppressed = {str(x.get("email") if isinstance(x, dict) else x).strip().lower() for x in suppressions}
    terminal = {"delivered", "bounced", "complained", "failed", "canceled", "cancelled"}
    for item in state.get("outbox", []) or []:
        if checked >= MAX_DELIVERY_CHECKS:
            break
        if item.get("source") != "outbound_engine" or item.get("status") != "sent" or item.get("email_provider") != "resend":
            continue
        message_id = str(item.get("email_provider_message_id") or "")
        if not message_id or str(item.get("provider_last_event") or "").lower() in terminal:
            continue
        event = _resend_event(message_id)
        checked += 1
        item["provider_checked_at"] = utcnow()
        if not event:
            continue
        item["provider_last_event"] = event
        if event in {"bounced", "complained", "failed", "canceled", "cancelled"}:
            email = str(item.get("contact") or "").strip().lower()
            if email and email not in suppressed:
                suppressions.append({"email": email, "reason": f"resend_{event}", "created_at": utcnow()})
                suppressed.add(email)
    state["email_suppression"] = suppressions[-1000:]
    return checked


def _reply_after(state: Dict[str, Any], contact: str, when: Any) -> bool:
    sent_at = _parse(when)
    for incoming in state.get("inbox", []) or []:
        if str(incoming.get("from") or "").strip().lower() != contact:
            continue
        received = _parse(incoming.get("received_at"))
        if not sent_at or (received and received >= sent_at):
            return True
    return False


def _refresh_sequences(state: Dict[str, Any]) -> None:
    messages = state.get("outbox", []) or []
    inbox = state.get("inbox", []) or []
    del inbox
    for seq in state.setdefault("outbound_sequences", []):
        mids = set(str(x) for x in seq.get("message_ids", []) or [])
        rows = [x for x in messages if str(x.get("id") or "") in mids]
        sent = [x for x in rows if x.get("status") == "sent"]
        delivered = [x for x in sent if str(x.get("provider_last_event") or "").lower() == "delivered"]
        contact = str(seq.get("contact") or "").strip().lower()
        first_sent = sorted(sent, key=lambda x: str(x.get("sent_at") or ""))[0] if sent else {}
        replied = bool(first_sent and _reply_after(state, contact, first_sent.get("sent_at")))
        if _suppressed(state, contact):
            seq["status"] = "suppressed"
        elif replied:
            seq["status"] = "replied"
        elif delivered:
            seq["status"] = "delivered"
        elif sent:
            seq["status"] = "sent"
        elif rows:
            seq["status"] = str(rows[-1].get("status") or "queued")
        seq["sent_messages"] = len(sent)
        seq["delivered_messages"] = len(delivered)
        seq["reply_detected"] = replied
        seq["updated_at"] = utcnow()


def _metrics(state: Dict[str, Any], prospects: List[Dict[str, Any]], new_queued: int, followups: int, delivery_checks: int, requeued: int) -> Dict[str, Any]:
    messages = [x for x in state.get("outbox", []) or [] if x.get("source") == "outbound_engine"]
    sent = [x for x in messages if x.get("status") == "sent"]
    delivered = [x for x in sent if str(x.get("provider_last_event") or "").lower() == "delivered"]
    failed = [x for x in messages if x.get("status") == "send_failed"]
    sequences = list(state.get("outbound_sequences", []) or [])
    replied = [x for x in sequences if x.get("reply_detected")]
    campaign_variants = {str(x.get("variant_id") or "") for x in sequences if x.get("variant_id")}
    campaign_clicks = sum(1 for x in state.get("acquisition_events", []) or [] if x.get("event") == "click" and str(x.get("variant_id") or "") in campaign_variants)
    exact_leads = sum(1 for seq in sequences if any(str(x.get("email") or "").strip().lower() == str(seq.get("contact") or "").strip().lower() for x in state.get("acquisition_leads", []) or []))
    account_ids = {str(x.get("account_id") or "") for x in sequences if x.get("account_id")}
    opportunities = 0
    for opp in list(state.get("market_opportunities", []) or []) + list(state.get("opportunities", []) or []):
        refs = {str(opp.get(k) or "") for k in ("buyer_account_id", "supplier_account_id", "account_id")}
        if refs & account_ids:
            opportunities += 1
    today = local_day()
    daily_new = _daily_new_count(state)
    avg_score = round(sum(float(x["score"]) for x in prospects) / max(1, len(prospects)), 1) if prospects else 0.0
    return {
        "version": VERSION,
        "updated_at": utcnow(),
        "status": "active" if LIVE else "prepared",
        "live": LIVE,
        "eligible_prospects": len(prospects),
        "average_prospect_score": avg_score,
        "new_queued_this_cycle": new_queued,
        "followups_queued_this_cycle": followups,
        "failed_requeued_this_cycle": requeued,
        "delivery_checks_this_cycle": delivery_checks,
        "messages_total": len(messages),
        "sent_total": len(sent),
        "delivered_verified": len(delivered),
        "send_failed": len(failed),
        "sequences_total": len(sequences),
        "replies_detected": len(replied),
        "campaign_variant_clicks": campaign_clicks,
        "leads_same_contact": exact_leads,
        "linked_opportunities": opportunities,
        "daily_new": daily_new,
        "daily_cap": MAX_NEW_PER_DAY,
        "daily_remaining": max(0, MAX_NEW_PER_DAY - daily_new),
        "provider": "resend" if RESEND_API_KEY else None,
        "attribution_note": "clicks are campaign-variant evidence; replies/leads by same corporate contact are direct evidence",
        "guardrails": {
            "verified_company_required": True,
            "verified_public_corporate_email_required": True,
            "opt_out_and_bounce_suppression": True,
            "counterparty_risk_gate": True,
            "communication_director_required": True,
            "quality_gate_required": True,
            "autonomous_coo_required_before_send": True,
            "max_new_per_day": MAX_NEW_PER_DAY,
            "recontact_days": RECONTACT_DAYS,
            "binding_commitments": False,
        },
    }


def outbound_engine_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    requeued = _requeue_failures(state)
    delivery_checks = _check_delivery(state)
    _refresh_sequences(state)
    prospects = _eligible(state)
    state["outbound_engine_prospects"] = [
        {
            "account_id": x["account"].get("id"),
            "company": _company(x["account"]),
            "role": x["account"].get("type"),
            "category": x["account"].get("category"),
            "score": x["score"],
            "reasons": x["reasons"],
        }
        for x in prospects[:100]
    ]
    followups = _queue_followups(state)
    new_queued = _queue_new(state, prospects)
    report = _metrics(state, prospects, new_queued, followups, delivery_checks, requeued)
    state["outbound_engine"] = report
    state.setdefault("activity", []).insert(0, {
        "ts": utcnow(),
        "msg": f"Outbound Engine: {new_queued} nuevos + {followups} seguimientos; {report['delivered_verified']} entregas Resend verificadas acumuladas."
    })
    state["activity"] = state["activity"][:100]
    return report


def _commercial_execution_with_outbound(state: Dict[str, Any]) -> Dict[str, Any]:
    base = dict(_ORIGINAL_COMMERCIAL_EXECUTION(state) or {})
    try:
        outbound = dict(outbound_engine_tick(state) or {})
    except Exception as exc:
        outbound = {"version": VERSION, "status": "degraded_fail_open", "error": f"{type(exc).__name__}: {str(exc)[:300]}", "updated_at": utcnow()}
        state["outbound_engine"] = outbound
    base["outbound_engine"] = outbound
    return base


if not getattr(commercial_execution, "_lumen_outbound_engine_installed", False):
    commercial_execution.commercial_execution_tick = _commercial_execution_with_outbound
    commercial_execution._lumen_outbound_engine_installed = True
