from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from urllib.parse import urlparse

from autonomy_governor import record_decision

try:
    from scout_connector import search as public_search, status as scout_status
except Exception:  # fail closed: screening remains unknown, never "clear"
    public_search = None
    scout_status = None

MAX_PROFILES = 180
MAX_PUBLIC_SCREENING_QUERIES_PER_CYCLE = 1
SCREENING_REFRESH_DAYS = 14
OFFICIAL_RESTRICTION_DOMAINS = (
    "ofac.treasury.gov",
    "sanctionssearch.ofac.treas.gov",
    "gov.uk",
    "un.org",
    "sanctionsmap.eu",
)


def utcnow_dt() -> datetime:
    return datetime.now(timezone.utc)


def utcnow() -> str:
    return utcnow_dt().strftime("%Y-%m-%d %H:%M:%S UTC")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S UTC", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _norm(value: Any) -> str:
    return " ".join(str(value or "").lower().strip().split())


def _domain(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if "@" in text and "://" not in text:
        return text.split("@", 1)[-1].removeprefix("www.")
    try:
        return (urlparse(text if "://" in text else "https://" + text).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _account_name(account: Dict[str, Any]) -> str:
    return str(account.get("company_name") or account.get("name_hint") or account.get("site_title") or account.get("domain") or "").strip()


def _relationship(state: Dict[str, Any], account_id: str) -> Dict[str, Any]:
    return next((x for x in state.get("commercial_relationships", []) or [] if str(x.get("account_id") or "") == account_id or str(x.get("key") or "") == f"account:{account_id}"), {})


def _linked_deals(state: Dict[str, Any], account_id: str) -> List[Dict[str, Any]]:
    return [x for x in state.get("deals", []) or [] if account_id in {str(x.get("buyer_account_id") or ""), str(x.get("supplier_account_id") or "")}]


def _incidents_for(state: Dict[str, Any], account_id: str) -> List[Dict[str, Any]]:
    deal_ids = {str(x.get("id")) for x in _linked_deals(state, account_id) if x.get("id")}
    return [x for x in state.get("commercial_incidents", []) or [] if str(x.get("deal_id") or "") in deal_ids and str(x.get("status") or "") not in {"resolved", "closed"}]


def _real_transactions_for(state: Dict[str, Any], account_id: str) -> List[Dict[str, Any]]:
    valid = {"closed", "invoiced", "delivered", "paid", "settled", "completed"}
    deal_ids = {str(x.get("id")) for x in _linked_deals(state, account_id) if x.get("id")}
    return [x for x in state.get("transactions", []) or [] if str(x.get("deal_id") or "") in deal_ids and str(x.get("status") or "") in valid]


def _email_domain_consistent(account: Dict[str, Any]) -> bool | None:
    company_domain = _domain(account.get("domain"))
    email_domain = _domain(account.get("commercial_email"))
    if not company_domain or not email_domain:
        return None
    return email_domain == company_domain or email_domain.endswith("." + company_domain)


def _screening_memory(state: Dict[str, Any]) -> Dict[str, Any]:
    memory = state.setdefault("counterparty_screening_memory", {})
    memory.setdefault("accounts", {})
    return memory


def _scout_budget_available(state: Dict[str, Any]) -> bool:
    budget = state.get("scout_budget", {}) or {}
    daily = int(budget.get("daily_budget") or 0)
    used = int(budget.get("queries_used") or 0)
    if daily <= 0:
        return False
    return used < daily


def _consume_scout_budget(state: Dict[str, Any]) -> None:
    budget = state.setdefault("scout_budget", {})
    budget["queries_used"] = int(budget.get("queries_used") or 0) + 1
    daily = int(budget.get("daily_budget") or 0)
    budget["queries_remaining"] = max(0, daily - budget["queries_used"]) if daily else 0


def _screening_due(row: Dict[str, Any]) -> bool:
    checked = _parse(row.get("checked_at"))
    return checked is None or utcnow_dt() >= checked + timedelta(days=SCREENING_REFRESH_DAYS)


def _official_domain(url: str) -> bool:
    host = _domain(url)
    return any(host == d or host.endswith("." + d) for d in OFFICIAL_RESTRICTION_DOMAINS)


def _name_present(name: str, item: Dict[str, Any]) -> bool:
    needle = _norm(name)
    hay = _norm(f"{item.get('title','')} {item.get('snippet','')}")
    if not needle or len(needle) < 4:
        return False
    return needle in hay


def _perform_one_public_screen(state: Dict[str, Any], accounts: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    if public_search is None or scout_status is None:
        return None
    try:
        status = scout_status() or {}
    except Exception:
        return None
    if not status.get("configured") or not _scout_budget_available(state):
        return None

    memory = _screening_memory(state)["accounts"]
    candidates = []
    for account in accounts:
        account_id = str(account.get("id") or "")
        name = _account_name(account)
        if not account_id or not name or not account.get("verified_company"):
            continue
        if not _screening_due(memory.get(account_id, {})):
            continue
        priority = _f((account.get("counterparty_scorecard") or {}).get("score"), _f(account.get("verification_score")))
        candidates.append((priority, account))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    account = candidates[0][1]
    account_id = str(account.get("id"))
    name = _account_name(account)
    query = f'"{name}" sanctions restricted debarred'
    try:
        results = list(public_search(query) or [])[:8]
        _consume_scout_budget(state)
    except Exception as exc:
        memory[account_id] = {
            "checked_at": utcnow(), "status": "screening_error", "query": query,
            "error": str(exc)[:240], "coverage": "partial_public_search_only",
        }
        return memory[account_id]

    official_hits = []
    other_hits = []
    for item in results:
        row = {"title": str(item.get("title") or "")[:300], "url": str(item.get("url") or ""), "snippet": str(item.get("snippet") or "")[:700]}
        if not _name_present(name, row):
            continue
        if _official_domain(row["url"]):
            official_hits.append(row)
        else:
            other_hits.append(row)

    result = {
        "checked_at": utcnow(),
        "status": "possible_official_match" if official_hits else "public_screen_completed_no_official_exact_name_hit",
        "query": query,
        "coverage": "partial_public_search_only",
        "official_hits": official_hits[:4],
        "other_name_hits": other_hits[:4],
        "rule": "No-hit is not legal clearance; any official-looking match requires human verification of entity identity and applicable law.",
    }
    memory[account_id] = result
    return result


def _profile(state: Dict[str, Any], account: Dict[str, Any]) -> Dict[str, Any]:
    account_id = str(account.get("id") or "")
    relation = _relationship(state, account_id)
    incidents = _incidents_for(state, account_id)
    transactions = _real_transactions_for(state, account_id)
    screening = (_screening_memory(state).get("accounts", {}) or {}).get(account_id, {})
    email_match = _email_domain_consistent(account)

    flags: List[str] = []
    blockers: List[str] = []
    review: List[str] = []

    if not account.get("verified_company"):
        blockers.append("company_unverified")
    if relation.get("opted_out") or relation.get("relationship_state") == "do_not_contact":
        blockers.append("do_not_contact")
    if email_match is False:
        review.append("commercial_email_domain_mismatch")
    if not account.get("commercial_channel_verified"):
        flags.append("commercial_channel_unverified")
    if incidents:
        review.append("open_commercial_incident")
    if screening.get("status") == "possible_official_match":
        blockers.append("possible_official_restriction_match_requires_human_verification")
    elif screening.get("status") in {None, "", "screening_error"}:
        flags.append("restriction_screening_not_completed")

    linked_deals = _linked_deals(state, account_id)
    if any(x.get("legal_review_required") for x in linked_deals):
        review.append("linked_deal_requires_legal_review")

    verification = max(0.0, min(100.0, _f(account.get("verification_score"))))
    identity = 40.0 if account.get("verified_company") else 0.0
    identity += min(20.0, verification * 0.20)
    contact = 15.0 if account.get("verified_contact") and email_match is not False else 8.0 if account.get("commercial_channel_verified") else 0.0
    behavior = 10.0 if transactions else 4.0 if relation.get("response_count") else 0.0
    screening_score = 10.0 if screening.get("status") == "public_screen_completed_no_official_exact_name_hit" else 0.0
    incident_penalty = min(30.0, len(incidents) * 15.0)
    review_penalty = min(25.0, len(review) * 8.0)
    score = max(0.0, min(100.0, identity + contact + behavior + screening_score - incident_penalty - review_penalty))

    if blockers:
        tier = "BLOCKED"
    elif review or score < 55:
        tier = "ENHANCED_REVIEW"
    elif score >= 78 and screening.get("status") == "public_screen_completed_no_official_exact_name_hit":
        tier = "STANDARD"
    else:
        tier = "WATCH"

    can_outreach = tier not in {"BLOCKED"} and not relation.get("opted_out")
    can_progress_commercially = tier in {"STANDARD", "WATCH"} and not incidents
    binding_requires_human = True

    profile = {
        "account_id": account_id,
        "name": _account_name(account),
        "type": account.get("type"),
        "domain": account.get("domain"),
        "risk_score": round(score, 1),
        "risk_tier": tier,
        "identity_score": round(identity, 1),
        "email_domain_consistent": email_match,
        "open_incidents": len(incidents),
        "real_transactions": len(transactions),
        "flags": flags,
        "review_reasons": review,
        "blockers": blockers,
        "screening": screening,
        "can_outreach": can_outreach,
        "can_progress_commercially": can_progress_commercially,
        "binding_requires_human": binding_requires_human,
        "updated_at": utcnow(),
        "method": "evidence_based_risk_triage_not_legal_clearance",
    }
    account["counterparty_risk"] = {
        "risk_score": profile["risk_score"], "risk_tier": tier, "flags": flags,
        "review_reasons": review, "blockers": blockers, "can_outreach": can_outreach,
        "can_progress_commercially": can_progress_commercially, "updated_at": profile["updated_at"],
    }
    return profile


def counterparty_risk_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    accounts = list(state.get("candidate_accounts", []) or [])
    public_screen = _perform_one_public_screen(state, accounts)
    profiles = [_profile(state, x) for x in accounts]
    profiles.sort(key=lambda x: ({"BLOCKED": 4, "ENHANCED_REVIEW": 3, "WATCH": 2, "STANDARD": 1}.get(str(x.get("risk_tier")), 0), -_f(x.get("risk_score"))), reverse=True)
    profiles = profiles[:MAX_PROFILES]
    index = {str(x.get("account_id")): x for x in profiles if x.get("account_id")}
    state["counterparty_risk_profiles"] = profiles
    state["counterparty_risk_index"] = index

    blocked = [x for x in profiles if x.get("risk_tier") == "BLOCKED"]
    enhanced = [x for x in profiles if x.get("risk_tier") == "ENHANCED_REVIEW"]
    directive = (blocked or enhanced or profiles[:1])[:1]
    report = {
        "updated_at": utcnow(),
        "mode": "counterparty_risk_and_compliance",
        "profiles_total": len(profiles),
        "blocked": len(blocked),
        "enhanced_review": len(enhanced),
        "standard": sum(1 for x in profiles if x.get("risk_tier") == "STANDARD"),
        "watch": sum(1 for x in profiles if x.get("risk_tier") == "WATCH"),
        "public_screening_this_cycle": public_screen,
        "primary_directive": directive[0] if directive else None,
        "governance": {
            "no_clearance_claim": "No-hit in public search is never represented as legal/sanctions clearance.",
            "official_match_rule": "A possible official restriction match blocks progression until a human verifies exact entity identity and applicable law.",
            "privacy_rule": "Uses corporate/public business evidence only; no inferred personal contacts.",
            "authority_rule": "Risk engine may block or demand evidence; it never approves contracts, payments or legal conclusions.",
        },
    }
    state["counterparty_risk"] = report
    if report.get("primary_directive"):
        p = report["primary_directive"]
        record_decision(
            state,
            engine="Counterparty Risk & Compliance",
            object_type="account",
            object_id=str(p.get("account_id") or ""),
            decision=f"risk_tier:{str(p.get('risk_tier') or '').lower()}",
            reason=f"Riesgo {p.get('risk_score')}/100; bloqueos: {', '.join(p.get('blockers') or []) or 'ninguno'}; revisión: {', '.join(p.get('review_reasons') or []) or 'ninguna'}.",
            action="score_opportunity",
            confidence=0.9 if p.get("risk_tier") == "BLOCKED" else 0.72,
            evidence_refs=[],
            allowed=p.get("risk_tier") != "BLOCKED",
            requires_approval=False,
        )
    return report
