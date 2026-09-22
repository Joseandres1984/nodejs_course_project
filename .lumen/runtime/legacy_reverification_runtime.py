from __future__ import annotations

"""Fresh, bounded re-verification bridge for recovered Railway commercial history.

Safety invariants:
- legacy verification flags/scores never establish current truth;
- legacy opt-outs remain blocked permanently;
- recently-contacted legacy rows observe a 30-day cooldown from the snapshot;
- only fresh public same-domain evidence may create a current candidate;
- the existing company_verifier remains the sole authority that can set
  verified_company=True;
- this bridge never sets verified_contact, commercial_email, or outbound eligibility.
"""

import hashlib
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Tuple

import app as lumen_app
import company_verifier

VERSION = "1.0-fresh-legacy-reverification"
RECOVERY_KEY = "railway_20260919"
MAX_PER_CYCLE = max(1, min(3, int(os.getenv("LUMEN_LEGACY_REVERIFY_PER_CYCLE", "2"))))
RETRY_HOURS = max(6, min(72, int(os.getenv("LUMEN_LEGACY_REVERIFY_RETRY_HOURS", "12"))))
LEGACY_RECONTACT_DAYS = max(30, min(180, int(os.getenv("LUMEN_LEGACY_RECONTACT_DAYS", "30"))))

CATEGORY_RULES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("automatización industrial", ("automatizacion", "automatización", "automation", "plc", "scada", "control industrial", "variador")),
    ("instrumentación y control", ("instrumentacion", "instrumentación", "instrument", "sensor", "transmisor", "manometro", "manómetro", "medicion", "medición")),
    ("material eléctrico y electrónica", ("electrico", "eléctrico", "electrical", "electronica", "electrónica", "tablero", "interruptor", "contactor", "cable")),
    ("mantenimiento industrial", ("mantenimiento", "maintenance", "reparacion", "reparación", "predictivo", "preventivo", "servicio tecnico", "servicio técnico")),
    ("maquinaria y equipos industriales", ("maquinaria", "machinery", "equipos industriales", "equipment", "motor", "bomba", "compresor", "valvula", "válvula")),
    ("seguridad industrial", ("seguridad industrial", "safety", "epp", "proteccion personal", "protección personal", "incendio", "extintor", "proteccion respiratoria", "protección respiratoria")),
    ("metrología y laboratorio", ("metrologia", "metrología", "calibracion", "calibración", "laboratorio", "laboratory", "patron", "patrón", "precision", "precisión")),
    ("herramientas y suministros industriales", ("herramientas", "tools", "suministros industriales", "insumos industriales", "ferreteria industrial", "ferretería industrial", "repuestos", "consumibles")),
    ("ingeniería y servicios técnicos", ("ingenieria", "ingeniería", "engineering", "proyectos industriales", "servicios tecnicos", "servicios técnicos", "montaje", "puesta en marcha")),
    ("logística y comercio exterior", ("logistica", "logística", "logistics", "transporte", "freight", "aduana", "comercio exterior", "importacion", "importación", "exportacion", "exportación")),
    ("tecnología B2B", ("software", "tecnologia", "tecnología", "technology", "sistemas", "cloud", "saas", "ciberseguridad", "cybersecurity")),
    ("productos químicos industriales", ("quimico", "químico", "chemical", "lubricante", "solvente", "adhesivo", "resina", "tratamiento de agua")),
)


def utcnow_dt() -> datetime:
    return datetime.now(timezone.utc)


def utcnow() -> str:
    return utcnow_dt().strftime("%Y-%m-%d %H:%M:%S UTC")


def _parse(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S UTC"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _contains_count(text: str, terms: Iterable[str]) -> int:
    low = (text or "").lower()
    return sum(1 for term in terms if str(term).lower() in low)


def _category(text: str) -> Tuple[str, int, List[str]]:
    low = (text or "").lower()
    scored: List[Tuple[int, str, List[str]]] = []
    for label, terms in CATEGORY_RULES:
        hits = [term for term in terms if term in low]
        score = len(hits)
        if score:
            scored.append((score, label, hits[:6]))
    if not scored:
        return "", 0, []
    scored.sort(key=lambda row: (-row[0], row[1]))
    score, label, hits = scored[0]
    # Require at least two independent live-text signals before assigning a commercial category.
    if score < 2:
        return "", score, hits
    return label, score, hits


def _role(text: str, legacy_hint: str) -> Tuple[str, Dict[str, int]]:
    supplier_hits = _contains_count(text, company_verifier.SUPPLIER_TERMS)
    buyer_hits = _contains_count(text, company_verifier.BUYER_CONTEXT_TERMS)
    hint = str(legacy_hint or "").strip().lower()

    # Historical type is only a tie-break hint after live evidence independently supports that role.
    if hint == "supplier" and supplier_hits >= 2:
        return "supplier", {"supplier_hits": supplier_hits, "buyer_hits": buyer_hits}
    if hint == "buyer" and buyer_hits >= 2 and supplier_hits < 2:
        return "buyer", {"supplier_hits": supplier_hits, "buyer_hits": buyer_hits}
    if supplier_hits >= 3 and supplier_hits >= buyer_hits:
        return "supplier", {"supplier_hits": supplier_hits, "buyer_hits": buyer_hits}
    if buyer_hits >= 3 and supplier_hits == 0:
        return "buyer", {"supplier_hits": supplier_hits, "buyer_hits": buyer_hits}
    return "unknown", {"supplier_hits": supplier_hits, "buyer_hits": buyer_hits}


def _existing_by_domain(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    for account in state.get("candidate_accounts", []) or []:
        if not isinstance(account, dict):
            continue
        domain = str(account.get("domain") or "").strip().lower().removeprefix("www.")
        if domain and domain not in result:
            result[domain] = account
    return result


def _apply_legacy_suppressions(state: Dict[str, Any], queue: List[Dict[str, Any]]) -> int:
    by_domain = _existing_by_domain(state)
    opt_out = state.setdefault("opt_out", [])
    opt_set = {str(x).strip().lower() for x in opt_out if str(x).strip()}
    applied = 0
    for row in queue:
        if not row.get("do_not_contact"):
            continue
        domain = str(row.get("official_domain") or "").strip().lower().removeprefix("www.")
        account = by_domain.get(domain)
        if not account:
            continue
        account["outbound_suppressed"] = True
        account["contact_policy"] = "do_not_contact"
        account["suppression_reason"] = "legacy_optout_preserved"
        account["legacy_optout_preserved_at"] = utcnow()
        email = str(account.get("commercial_email") or "").strip().lower()
        if email and email not in opt_set:
            opt_out.append(email)
            opt_set.add(email)
        applied += 1
    return applied


def _reconcile(state: Dict[str, Any], queue: List[Dict[str, Any]]) -> Dict[str, int]:
    accounts = {str(a.get("id") or ""): a for a in state.get("candidate_accounts", []) or [] if isinstance(a, dict)}
    stats = {"linked_verified": 0, "linked_insufficient": 0, "linked_retry": 0, "linked_contact_verified": 0}
    for row in queue:
        account_id = str(row.get("current_candidate_id") or "")
        if not account_id:
            continue
        account = accounts.get(account_id)
        if not account:
            continue
        if account.get("verified_company"):
            row["status"] = "fresh_company_verified"
            row["fresh_company_verified_at"] = account.get("verified_at") or utcnow()
            row["current_verification_score"] = account.get("verification_score")
            row["fresh_evidence_urls"] = list(account.get("evidence_urls") or [])[:4]
            row["safe_for_outbound"] = False
            stats["linked_verified"] += 1
            if account.get("verified_contact") and account.get("commercial_email"):
                row["fresh_contact_verified"] = True
                row["fresh_contact_verified_at"] = account.get("commercial_contact_researched_at") or utcnow()
                stats["linked_contact_verified"] += 1
        elif account.get("verification_status") == "evidence_insufficient":
            row["status"] = "fresh_evidence_insufficient"
            row["current_verification_score"] = account.get("verification_score")
            row["fresh_evidence_urls"] = list(account.get("evidence_urls") or [])[:4]
            row["safe_for_outbound"] = False
            stats["linked_insufficient"] += 1
        elif account.get("verification_status") == "retry_required":
            row["status"] = "current_verification_retry"
            row["safe_for_outbound"] = False
            stats["linked_retry"] += 1
    return stats


def _cooldown_until(recovery: Dict[str, Any]) -> datetime:
    snapshot = _parse(recovery.get("snapshot_at")) or utcnow_dt()
    return snapshot + timedelta(days=LEGACY_RECONTACT_DAYS)


def _due(row: Dict[str, Any], recovery: Dict[str, Any], now: datetime) -> bool:
    if row.get("do_not_contact"):
        return False
    if str(row.get("legacy_reason") or "") == "recent_successful_contact_window":
        until = _cooldown_until(recovery)
        row["status"] = "legacy_contact_cooldown" if now < until else "pending_reverification"
        row["eligible_after"] = until.strftime("%Y-%m-%d %H:%M:%S UTC")
        if now < until:
            return False
    status = str(row.get("status") or "")
    if status == "pending_reverification":
        return True
    if status in {"retry_required", "fresh_classification_retry"}:
        attempted = _parse(row.get("fresh_reverification_attempted_at"))
        return attempted is None or now - attempted >= timedelta(hours=RETRY_HOURS)
    return False


def _candidate_id(domain: str) -> str:
    return "ACC-LR-" + hashlib.sha1(("railway-reverify|" + domain).encode("utf-8")).hexdigest()[:12].upper()


def _classify_fresh(row: Dict[str, Any]) -> Dict[str, Any]:
    domain = str(row.get("official_domain") or "").strip().lower().removeprefix("www.")
    if not domain:
        return {"status": "invalid", "reason": "missing_official_domain"}

    probe = {"domain": domain, "source_url": f"https://{domain}/", "category": "", "type": "unknown"}
    pages, error = company_verifier._collect_evidence(probe)
    if not pages:
        return {"status": "retry", "reason": error or "no_live_html"}

    combined_parts: List[str] = []
    evidence_urls: List[str] = []
    title = ""
    description = ""
    for index, page in enumerate(pages):
        html = str(page.get("html") or "")
        if index == 0:
            title = company_verifier._title(html)
            description = company_verifier._description(html)
        evidence_urls.append(str(page.get("url") or ""))
        combined_parts.append(company_verifier._clean_text(html)[:75_000])
    combined = f"{title} {description} " + " ".join(combined_parts)
    business_hits = _contains_count(combined, company_verifier.BUSINESS_TERMS)
    category, category_hits, category_terms = _category(combined)
    role, role_hits = _role(combined, str(row.get("type") or ""))

    if business_hits < 2:
        return {
            "status": "insufficient",
            "reason": "fresh_site_lacks_corporate_signals",
            "evidence_urls": evidence_urls[:4],
            "business_hits": business_hits,
            "title": title,
        }
    if not category:
        return {
            "status": "insufficient",
            "reason": "fresh_category_not_established",
            "evidence_urls": evidence_urls[:4],
            "business_hits": business_hits,
            "category_hits": category_hits,
            "category_terms": category_terms,
            "title": title,
        }
    if role not in {"buyer", "supplier"}:
        return {
            "status": "insufficient",
            "reason": "fresh_commercial_role_not_established",
            "evidence_urls": evidence_urls[:4],
            "business_hits": business_hits,
            "category": category,
            "category_terms": category_terms,
            "role_hits": role_hits,
            "title": title,
        }

    return {
        "status": "classified",
        "domain": domain,
        "source_url": evidence_urls[0] if evidence_urls else f"https://{domain}/",
        "name_hint": title or domain,
        "category": category,
        "type": role,
        "fresh_business_hits": business_hits,
        "fresh_category_terms": category_terms,
        "fresh_role_hits": role_hits,
        "fresh_evidence_urls": evidence_urls[:4],
        "pages_reviewed_for_classification": len(pages),
    }


def _queue_current_candidate(state: Dict[str, Any], row: Dict[str, Any], fresh: Dict[str, Any]) -> Dict[str, Any]:
    accounts = state.setdefault("candidate_accounts", [])
    domain = str(fresh["domain"])
    existing = _existing_by_domain(state).get(domain)
    if existing:
        row["status"] = "linked_existing_current"
        row["current_candidate_id"] = existing.get("id")
        row["safe_for_outbound"] = False
        return {"created": False, "linked": True, "account_id": existing.get("id")}

    account_id = _candidate_id(domain)
    candidate = {
        "id": account_id,
        "candidate_key": "|".join([str(fresh["type"]), str(fresh["category"]).lower(), domain]),
        "type": fresh["type"],
        "category": fresh["category"],
        "name_hint": fresh["name_hint"],
        "domain": domain,
        "source_url": fresh["source_url"],
        "lead_score": 0,
        "confidence": 0.55,
        "status": "verification_required",
        "verification_status": "verification_required",
        "verified_company": False,
        "verified_contact": False,
        "contact_policy": "public_corporate_channels_only",
        "legacy_reverification": True,
        "legacy_recovery_key": RECOVERY_KEY,
        "legacy_ids": list(row.get("legacy_ids") or [])[:8],
        "legacy_verification_trusted": False,
        "fresh_classification_evidence": list(fresh.get("fresh_evidence_urls") or [])[:4],
        "fresh_category_terms": list(fresh.get("fresh_category_terms") or [])[:6],
        "fresh_role_hits": dict(fresh.get("fresh_role_hits") or {}),
        "fresh_business_hits": fresh.get("fresh_business_hits"),
        "created_at": utcnow(),
        "next_action": "Ejecutar verificación corporativa vigente y luego investigar sólo canales corporativos públicos",
    }
    accounts.append(candidate)
    row.update({
        "status": "queued_current_verification",
        "current_candidate_id": account_id,
        "fresh_category": fresh["category"],
        "fresh_type": fresh["type"],
        "fresh_classification_evidence": list(fresh.get("fresh_evidence_urls") or [])[:4],
        "fresh_classified_at": utcnow(),
        "safe_for_outbound": False,
    })
    return {"created": True, "linked": False, "account_id": account_id}


def tick(state: Dict[str, Any]) -> Dict[str, Any]:
    root = state.get("legacy_recovery") or {}
    recovery = root.get(RECOVERY_KEY) if isinstance(root, dict) else None
    if not isinstance(recovery, dict):
        return {"version": VERSION, "status": "legacy_archive_not_imported", "attempted": 0, "created": 0}

    queue = recovery.get("reverification_queue")
    if not isinstance(queue, list):
        return {"version": VERSION, "status": "legacy_queue_missing", "attempted": 0, "created": 0}

    suppressed_applied = _apply_legacy_suppressions(state, queue)
    reconciled = _reconcile(state, queue)
    now = utcnow_dt()
    due = [row for row in queue if isinstance(row, dict) and _due(row, recovery, now)]
    due.sort(key=lambda row: (-float(row.get("priority") or 0.0), str(row.get("official_domain") or "")))

    stats: Dict[str, Any] = {
        "version": VERSION,
        "status": "active",
        "attempted": 0,
        "classified": 0,
        "created": 0,
        "linked_existing": 0,
        "retry": 0,
        "insufficient": 0,
        "invalid": 0,
        "suppressed_applied_to_current": suppressed_applied,
        **reconciled,
    }
    for row in due[:MAX_PER_CYCLE]:
        stats["attempted"] += 1
        row["fresh_reverification_attempted_at"] = utcnow()
        row["fresh_reverification_attempts"] = int(row.get("fresh_reverification_attempts") or 0) + 1
        row["safe_for_outbound"] = False
        result = _classify_fresh(row)
        status = result.get("status")
        if status == "classified":
            stats["classified"] += 1
            queued = _queue_current_candidate(state, row, result)
            stats["created"] += 1 if queued.get("created") else 0
            stats["linked_existing"] += 1 if queued.get("linked") else 0
        elif status == "retry":
            row["status"] = "fresh_classification_retry"
            row["fresh_reverification_error"] = str(result.get("reason") or "retry")[:200]
            stats["retry"] += 1
        elif status == "insufficient":
            row["status"] = "fresh_evidence_insufficient"
            row["fresh_reverification_reason"] = result.get("reason")
            row["fresh_classification_evidence"] = list(result.get("evidence_urls") or [])[:4]
            row["fresh_business_hits"] = result.get("business_hits")
            row["fresh_category_hits"] = result.get("category_hits")
            row["fresh_category_terms"] = list(result.get("category_terms") or [])[:6]
            row["fresh_role_hits"] = dict(result.get("role_hits") or {})
            stats["insufficient"] += 1
        else:
            row["status"] = "fresh_evidence_invalid"
            row["fresh_reverification_reason"] = str(result.get("reason") or "invalid")[:200]
            stats["invalid"] += 1

    statuses: Dict[str, int] = {}
    for row in queue:
        if isinstance(row, dict):
            key = str(row.get("status") or "unknown")
            statuses[key] = statuses.get(key, 0) + 1
    stats["queue_status_counts"] = statuses
    stats["max_per_cycle"] = MAX_PER_CYCLE
    stats["legacy_verification_trusted"] = False
    stats["bridge_sets_verified_company"] = False
    stats["bridge_sets_verified_contact"] = False
    stats["bridge_sets_outbound_safe"] = False
    stats["updated_at"] = utcnow()
    recovery["fresh_reverification_runtime"] = stats
    return stats


def run_once() -> Dict[str, Any]:
    if not lumen_app.load_state():
        return {"version": VERSION, "status": "state_unavailable_fail_closed", "attempted": 0, "created": 0, "persisted": False}
    stats = tick(lumen_app.STATE)
    persisted = bool(lumen_app.save_state())
    result = {**stats, "persisted": persisted}
    print({"legacy_reverification_runtime": result}, flush=True)
    return result
