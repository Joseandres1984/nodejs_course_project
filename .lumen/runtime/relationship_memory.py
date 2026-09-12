from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from autonomy_governor import record_decision

FOLLOW_UP_DAYS = 4
MAX_FOLLOW_UPS_WITHOUT_REPLY = 2


def utcnow_dt() -> datetime:
    return datetime.now(timezone.utc)


def utcnow() -> str:
    return utcnow_dt().strftime("%Y-%m-%d %H:%M:%S UTC")


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S UTC", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _log(state: Dict[str, Any], message: str) -> None:
    state.setdefault("activity", []).insert(0, {"ts": utcnow(), "msg": message})
    state["activity"] = state["activity"][:100]


def _relation_key(counterparty: str = "", account_id: str = "", domain: str = "") -> str:
    if account_id:
        return f"account:{account_id}"
    if domain:
        return f"domain:{domain.lower()}"
    return f"counterparty:{counterparty.strip().lower()}"


def _ensure_relation(relations: Dict[str, Dict[str, Any]], key: str) -> Dict[str, Any]:
    if key not in relations:
        relations[key] = {
            "key": key,
            "counterparty": None,
            "account_id": None,
            "domain": None,
            "categories": [],
            "outbound_count": 0,
            "response_count": 0,
            "follow_up_count": 0,
            "last_outbound_at": None,
            "last_inbound_at": None,
            "last_interaction_at": None,
            "opted_out": False,
            "commercial_channel": None,
            "commercial_email": None,
            "relationship_state": "prospect",
            "next_follow_up_at": None,
            "follow_up_due": False,
            "created_at": utcnow(),
        }
    return relations[key]


def _latest(a: Any, b: Any) -> str | None:
    da, db = _parse(a), _parse(b)
    if da and db:
        return a if da >= db else b
    return a or b


def relationship_tick(state: Dict[str, Any]) -> Dict[str, int]:
    existing = {str(x.get("key")): x for x in state.setdefault("commercial_relationships", []) if x.get("key")}
    opt_out = {str(x).strip().lower() for x in state.setdefault("opt_out", [])}
    stats = {"accounts": 0, "outbound_events": 0, "inbound_events": 0, "follow_up_due": 0, "cooldown": 0, "opt_out": 0}

    for account in state.get("candidate_accounts", []):
        key = _relation_key(account_id=str(account.get("id") or ""), domain=str(account.get("domain") or ""))
        relation = _ensure_relation(existing, key)
        relation["account_id"] = account.get("id")
        relation["domain"] = account.get("domain")
        relation["counterparty"] = account.get("name_hint") or relation.get("counterparty")
        category = account.get("category")
        if category and category not in relation["categories"]:
            relation["categories"].append(category)
        relation["commercial_channel"] = account.get("contact_channel") or relation.get("commercial_channel")
        relation["commercial_email"] = account.get("commercial_email") or relation.get("commercial_email")
        if relation.get("commercial_email") and str(relation["commercial_email"]).lower() in opt_out:
            relation["opted_out"] = True
        stats["accounts"] += 1

    # Rebuild observable interaction counters from persisted messages so the process is idempotent.
    for relation in existing.values():
        relation["outbound_count"] = 0
        relation["response_count"] = 0
        relation["follow_up_count"] = 0
        relation["last_outbound_at"] = None
        relation["last_inbound_at"] = None

    contact_to_relation: Dict[str, Dict[str, Any]] = {}
    name_to_relation: Dict[str, Dict[str, Any]] = {}
    for relation in existing.values():
        if relation.get("commercial_email"):
            contact_to_relation[str(relation["commercial_email"]).lower()] = relation
        if relation.get("counterparty"):
            name_to_relation[str(relation["counterparty"]).strip().lower()] = relation

    for message in state.get("outbox", []):
        contact = str(message.get("contact") or "").strip().lower()
        name = str(message.get("counterparty") or "").strip().lower()
        relation = contact_to_relation.get(contact) or name_to_relation.get(name)
        if relation is None and (contact or name):
            key = _relation_key(counterparty=name or contact)
            relation = _ensure_relation(existing, key)
            relation["counterparty"] = message.get("counterparty") or contact
            if contact:
                relation["commercial_email"] = contact
                contact_to_relation[contact] = relation
            if name:
                name_to_relation[name] = relation
        if relation is None:
            continue
        if message.get("status") == "sent":
            relation["outbound_count"] += 1
            if message.get("kind") == "follow_up":
                relation["follow_up_count"] += 1
            relation["last_outbound_at"] = _latest(relation.get("last_outbound_at"), message.get("sent_at") or message.get("created_at"))
            stats["outbound_events"] += 1

    for incoming in state.get("inbox", []):
        sender = str(incoming.get("from") or "").strip().lower()
        relation = contact_to_relation.get(sender)
        if relation is None:
            continue
        relation["response_count"] += 1
        relation["last_inbound_at"] = _latest(relation.get("last_inbound_at"), incoming.get("received_at"))
        stats["inbound_events"] += 1

    now = utcnow_dt()
    actions: List[Dict[str, Any]] = []
    for relation in existing.values():
        relation["last_interaction_at"] = _latest(relation.get("last_outbound_at"), relation.get("last_inbound_at"))
        email = str(relation.get("commercial_email") or "").lower()
        relation["opted_out"] = bool(relation.get("opted_out") or (email and email in opt_out))
        relation["follow_up_due"] = False
        relation["next_follow_up_at"] = None

        if relation["opted_out"]:
            relation["relationship_state"] = "do_not_contact"
            stats["opt_out"] += 1
            continue

        outbound_at = _parse(relation.get("last_outbound_at"))
        inbound_at = _parse(relation.get("last_inbound_at"))
        awaiting_reply = bool(outbound_at and (not inbound_at or inbound_at < outbound_at))
        if awaiting_reply:
            due_at = outbound_at + timedelta(days=FOLLOW_UP_DAYS)
            relation["next_follow_up_at"] = due_at.strftime("%Y-%m-%d %H:%M:%S UTC")
            if relation.get("follow_up_count", 0) >= MAX_FOLLOW_UPS_WITHOUT_REPLY:
                relation["relationship_state"] = "cooldown"
                stats["cooldown"] += 1
            elif now >= due_at:
                relation["relationship_state"] = "follow_up_due"
                relation["follow_up_due"] = True
                stats["follow_up_due"] += 1
                actions.append({
                    "kind": "respectful_follow_up",
                    "relationship_key": relation["key"],
                    "counterparty": relation.get("counterparty"),
                    "contact": relation.get("commercial_email"),
                    "reason": "Sin respuesta luego del período de cortesía; máximo dos seguimientos antes de cooldown.",
                    "created_at": utcnow(),
                })
            else:
                relation["relationship_state"] = "awaiting_reply"
        elif inbound_at:
            relation["relationship_state"] = "engaged"
        elif relation.get("commercial_channel"):
            relation["relationship_state"] = "reachable"
        else:
            relation["relationship_state"] = "prospect"

    state["commercial_relationships"] = list(existing.values())
    state["relationship_actions"] = actions[:50]
    state["relationship_policy"] = {
        "follow_up_days": FOLLOW_UP_DAYS,
        "max_follow_ups_without_reply": MAX_FOLLOW_UPS_WITHOUT_REPLY,
        "principle": "persistencia profesional sin hostigamiento",
        "updated_at": utcnow(),
    }
    state["relationship_stats"] = {**stats, "relationships": len(existing), "updated_at": utcnow()}
    if stats["follow_up_due"] or stats["cooldown"]:
        _log(state, f"Relationship Memory: {stats['follow_up_due']} seguimientos debidos y {stats['cooldown']} relaciones en cooldown.")
    return stats
