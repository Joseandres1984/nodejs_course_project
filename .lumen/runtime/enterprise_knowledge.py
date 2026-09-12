from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List

from autonomy_governor import record_decision

MAX_NODES = 2200
MAX_EDGES = 6000
MAX_PRICE_HISTORY = 600
MAX_PROVENANCE = 10


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _norm(value: Any) -> str:
    return " ".join(str(value or "").lower().strip().split())


def _known(value: Any) -> bool:
    return value not in (None, "", [], {}, "unknown", "por validar")


def _stable(prefix: str, value: Any) -> str:
    raw = _norm(value)
    return f"{prefix}:{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:14]}" if raw else f"{prefix}:unknown"


def _node_id(kind: str, external_id: Any = None, label: Any = None) -> str:
    if external_id:
        return f"{kind}:{external_id}"
    return _stable(kind, label)


def _edge_id(subject: str, predicate: str, obj: str) -> str:
    raw = f"{subject}|{predicate}|{obj}"
    return "EDGE-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:18]


def _clean_attrs(attrs: Dict[str, Any]) -> Dict[str, Any]:
    return {str(k): v for k, v in attrs.items() if _known(v)}


def _upsert_node(
    nodes: Dict[str, Dict[str, Any]], *, node_id: str, kind: str, label: str,
    attrs: Dict[str, Any] | None = None, evidence: str | None = None, confidence: float = 0.9,
) -> str:
    now = utcnow()
    node = nodes.setdefault(node_id, {
        "id": node_id,
        "kind": kind,
        "label": label,
        "attrs": {},
        "first_seen_at": now,
        "last_seen_at": now,
        "confidence": round(confidence, 2),
        "provenance": [],
    })
    node["label"] = label or node.get("label")
    node["last_seen_at"] = now
    node["confidence"] = round(max(float(node.get("confidence") or 0), float(confidence)), 2)
    node.setdefault("attrs", {}).update(_clean_attrs(attrs or {}))
    if evidence:
        node.setdefault("provenance", [])
        if evidence not in node["provenance"]:
            node["provenance"].append(evidence)
            node["provenance"] = node["provenance"][-MAX_PROVENANCE:]
    return node_id


def _upsert_edge(
    edges: Dict[str, Dict[str, Any]], *, subject: str, predicate: str, obj: str,
    evidence: str | None = None, confidence: float = 0.9, attrs: Dict[str, Any] | None = None,
) -> None:
    eid = _edge_id(subject, predicate, obj)
    now = utcnow()
    edge = edges.setdefault(eid, {
        "id": eid,
        "subject": subject,
        "predicate": predicate,
        "object": obj,
        "attrs": {},
        "confidence": round(confidence, 2),
        "first_seen_at": now,
        "last_seen_at": now,
        "provenance": [],
    })
    edge["last_seen_at"] = now
    edge["confidence"] = round(max(float(edge.get("confidence") or 0), float(confidence)), 2)
    edge.setdefault("attrs", {}).update(_clean_attrs(attrs or {}))
    if evidence:
        if evidence not in edge.setdefault("provenance", []):
            edge["provenance"].append(evidence)
            edge["provenance"] = edge["provenance"][-MAX_PROVENANCE:]


def _company_node(nodes: Dict[str, Dict[str, Any]], account: Dict[str, Any]) -> str:
    label = str(account.get("company_name") or account.get("name_hint") or account.get("site_title") or account.get("domain") or "Empresa")
    nid = _node_id("company", account.get("id"), label)
    return _upsert_node(
        nodes,
        node_id=nid,
        kind="company",
        label=label,
        attrs={
            "account_id": account.get("id"),
            "type": account.get("type"),
            "domain": account.get("domain"),
            "country": account.get("country") or account.get("market"),
            "verified_company": bool(account.get("verified_company")),
            "verification_score": account.get("verification_score"),
            "commercial_email": account.get("commercial_email") if account.get("verified_contact") else None,
            "commercial_channel_verified": bool(account.get("commercial_channel_verified")),
        },
        evidence=str(account.get("official_url") or account.get("source_url") or "") or None,
        confidence=0.98 if account.get("verified_company") else 0.6,
    )


def _category_node(nodes: Dict[str, Dict[str, Any]], category: Any) -> str | None:
    if not _known(category):
        return None
    label = str(category).strip()
    nid = _node_id("category", label=label)
    _upsert_node(nodes, node_id=nid, kind="category", label=label, confidence=0.92)
    return nid


def _build_graph(state: Dict[str, Any]) -> Dict[str, Any]:
    previous = state.get("enterprise_knowledge_graph", {}) or {}
    nodes = {str(x.get("id")): x for x in previous.get("nodes", []) if x.get("id")}
    edges = {str(x.get("id")): x for x in previous.get("edges", []) if x.get("id")}
    accounts = {str(x.get("id")): x for x in state.get("candidate_accounts", []) if x.get("id")}
    account_node: Dict[str, str] = {}

    for account_id, account in accounts.items():
        company = _company_node(nodes, account)
        account_node[account_id] = company
        category = _category_node(nodes, account.get("category"))
        if category:
            predicate = "buys_category" if account.get("type") == "buyer" else "supplies_category"
            _upsert_edge(edges, subject=company, predicate=predicate, obj=category, confidence=0.9)
        if account.get("verified_contact") and account.get("commercial_email"):
            contact_id = _node_id("contact_channel", label=account.get("commercial_email"))
            _upsert_node(
                nodes,
                node_id=contact_id,
                kind="contact_channel",
                label=str(account.get("commercial_email")),
                attrs={"channel": "email", "verified": True},
                evidence=str(account.get("contact_source_url") or "") or None,
                confidence=0.98,
            )
            _upsert_edge(edges, subject=company, predicate="has_verified_contact", obj=contact_id, confidence=0.98)

    opportunity_by_id: Dict[str, Dict[str, Any]] = {}
    for opp in list(state.get("market_opportunities", [])) + list(state.get("opportunities", [])):
        if not opp.get("id"):
            continue
        oid = str(opp.get("id"))
        opportunity_by_id[oid] = opp
        onode = _node_id("opportunity", oid)
        _upsert_node(
            nodes,
            node_id=onode,
            kind="opportunity",
            label=oid,
            attrs={
                "category": opp.get("category") or opp.get("need"),
                "score": opp.get("score"),
                "portfolio_priority_score": opp.get("portfolio_priority_score"),
                "requirement_confirmed": opp.get("requirement_confirmed"),
                "source": opp.get("source"),
            },
            evidence=(opp.get("evidence_refs") or [None])[0],
            confidence=min(0.98, max(0.5, float(opp.get("score") or 50) / 100.0)),
        )
        category = _category_node(nodes, opp.get("category") or opp.get("need"))
        if category:
            _upsert_edge(edges, subject=onode, predicate="concerns_category", obj=category, confidence=0.95)
        buyer = account_node.get(str(opp.get("buyer_account_id") or ""))
        supplier = account_node.get(str(opp.get("supplier_account_id") or ""))
        if buyer:
            _upsert_edge(edges, subject=buyer, predicate="has_opportunity", obj=onode, confidence=0.95)
        if supplier:
            _upsert_edge(edges, subject=supplier, predicate="supports_opportunity", obj=onode, confidence=0.92)

    deal_by_id = {str(x.get("id")): x for x in state.get("deals", []) if x.get("id")}
    for deal_id, deal in deal_by_id.items():
        dnode = _node_id("deal", deal_id)
        _upsert_node(
            nodes,
            node_id=dnode,
            kind="deal",
            label=deal_id,
            attrs={
                "stage": deal.get("stage"),
                "need": deal.get("need"),
                "close_prob": deal.get("close_prob"),
                "company_profit": deal.get("company_profit"),
                "company_share_pct": deal.get("company_share_pct"),
                "economic_value_known": deal.get("economic_value_known"),
            },
            confidence=0.95,
        )
        opp_id = str(deal.get("opportunity_id") or "")
        if opp_id:
            _upsert_edge(edges, subject=dnode, predicate="derived_from", obj=_node_id("opportunity", opp_id), confidence=0.98)
        buyer = account_node.get(str(deal.get("buyer_account_id") or ""))
        supplier = account_node.get(str(deal.get("supplier_account_id") or ""))
        if buyer:
            _upsert_edge(edges, subject=dnode, predicate="buyer", obj=buyer, confidence=0.98)
        if supplier:
            _upsert_edge(edges, subject=dnode, predicate="primary_supplier", obj=supplier, confidence=0.9)
        category = _category_node(nodes, deal.get("need"))
        if category:
            _upsert_edge(edges, subject=dnode, predicate="concerns_category", obj=category, confidence=0.95)

    for doc in state.get("document_registry", []):
        if not doc.get("id"):
            continue
        doc_id = str(doc.get("id"))
        dnode = _node_id("document", doc_id)
        _upsert_node(
            nodes,
            node_id=dnode,
            kind="document",
            label=str(doc.get("filename") or doc_id),
            attrs={
                "document_type": doc.get("document_type"),
                "sha256": doc.get("sha256"),
                "extraction_status": doc.get("extraction_status"),
                "quote_number": (doc.get("facts") or {}).get("quote_number"),
            },
            evidence=str((doc.get("source_messages") or [""])[-1]),
            confidence=float(doc.get("document_type_confidence") or 0.55),
        )
        sender = next((x for x in state.get("candidate_accounts", []) if _norm(x.get("commercial_email")) == _norm(doc.get("sender"))), None)
        if sender and str(sender.get("id")) in account_node:
            _upsert_edge(edges, subject=dnode, predicate="received_from", obj=account_node[str(sender.get("id"))], confidence=0.98)

    offer_by_id = {str(x.get("id")): x for x in state.get("offers", []) if x.get("id")}
    for offer_id, offer in offer_by_id.items():
        if offer.get("source") == "demo/simulación":
            continue
        qnode = _node_id("quote", offer_id)
        _upsert_node(
            nodes,
            node_id=qnode,
            kind="quote",
            label=offer_id,
            attrs={
                "supplier": offer.get("supplier"),
                "amount": offer.get("amount"),
                "currency": offer.get("currency"),
                "lead_days": offer.get("lead_days"),
                "payment_terms": offer.get("payment_terms"),
                "validity_days": offer.get("validity_days"),
                "warranty": offer.get("warranty"),
                "incoterm": offer.get("incoterm"),
                "comparable": offer.get("comparable"),
                "source": offer.get("source"),
            },
            evidence=str(offer.get("document_id") or offer.get("source_message_id") or "") or None,
            confidence=0.98 if offer.get("source_traceable") else 0.82,
        )
        deal_id = str(offer.get("deal_id") or "")
        if deal_id:
            _upsert_edge(edges, subject=qnode, predicate="for_deal", obj=_node_id("deal", deal_id), confidence=0.99)
        supplier = account_node.get(str(offer.get("supplier_account_id") or ""))
        if supplier:
            _upsert_edge(edges, subject=qnode, predicate="quoted_by", obj=supplier, confidence=0.99)
        if offer.get("document_id"):
            _upsert_edge(edges, subject=qnode, predicate="extracted_from", obj=_node_id("document", offer.get("document_id")), confidence=0.99)

    for neg in state.get("negotiations", []):
        if not neg.get("id"):
            continue
        nnode = _node_id("negotiation", neg.get("id"))
        _upsert_node(nodes, node_id=nnode, kind="negotiation", label=str(neg.get("id")), attrs={
            "action": neg.get("action"), "company_share_pct": neg.get("company_share_pct")
        }, confidence=0.94)
        if neg.get("deal_id"):
            _upsert_edge(edges, subject=nnode, predicate="for_deal", obj=_node_id("deal", neg.get("deal_id")), confidence=0.98)

    for txn in state.get("transactions", []):
        if str(txn.get("status") or "") in {"simulated", "closed_simulated"} or not txn.get("id"):
            continue
        tnode = _node_id("transaction", txn.get("id"))
        _upsert_node(nodes, node_id=tnode, kind="transaction", label=str(txn.get("id")), attrs={
            "status": txn.get("status"), "amount": txn.get("amount"), "currency": txn.get("currency"),
            "company_profit": txn.get("company_profit"),
        }, confidence=0.99)
        if txn.get("deal_id"):
            _upsert_edge(edges, subject=tnode, predicate="settles_deal", obj=_node_id("deal", txn.get("deal_id")), confidence=0.99)

    node_rows = list(nodes.values())[-MAX_NODES:]
    valid_ids = {str(x.get("id")) for x in node_rows}
    edge_rows = [x for x in edges.values() if x.get("subject") in valid_ids and x.get("object") in valid_ids][-MAX_EDGES:]
    return {"nodes": node_rows, "edges": edge_rows}


def _price_history(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    deals = {str(x.get("id")): x for x in state.get("deals", []) if x.get("id")}
    rows: List[Dict[str, Any]] = []
    for offer in state.get("offers", []):
        if offer.get("source") == "demo/simulación" or not _known(offer.get("amount")) or not _known(offer.get("currency")):
            continue
        deal = deals.get(str(offer.get("deal_id") or ""), {})
        category = deal.get("need")
        if not category:
            continue
        rows.append({
            "quote_id": offer.get("id"),
            "document_id": offer.get("document_id"),
            "deal_id": offer.get("deal_id"),
            "category": category,
            "supplier": offer.get("supplier"),
            "supplier_account_id": offer.get("supplier_account_id"),
            "amount": offer.get("amount"),
            "currency": offer.get("currency"),
            "lead_days": offer.get("lead_days"),
            "payment_terms": offer.get("payment_terms"),
            "created_at": offer.get("created_at"),
            "source": offer.get("source"),
            "usage_rule": "historical_evidence_only_not_current_price",
        })
    return rows[-MAX_PRICE_HISTORY:]


def _category_memory(state: Dict[str, Any], prices: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    buckets: Dict[str, Dict[str, Any]] = {}
    for account in state.get("candidate_accounts", []):
        category = str(account.get("category") or "").strip()
        if not category:
            continue
        row = buckets.setdefault(category, {"category": category, "verified_buyers": 0, "verified_suppliers": 0, "quotes": 0, "deals": 0, "real_transactions": 0, "currencies": set()})
        if account.get("verified_company") and account.get("type") == "buyer":
            row["verified_buyers"] += 1
        if account.get("verified_company") and account.get("type") == "supplier":
            row["verified_suppliers"] += 1
    for deal in state.get("deals", []):
        category = str(deal.get("need") or "").strip()
        if category:
            buckets.setdefault(category, {"category": category, "verified_buyers": 0, "verified_suppliers": 0, "quotes": 0, "deals": 0, "real_transactions": 0, "currencies": set()})["deals"] += 1
    for price in prices:
        category = str(price.get("category") or "").strip()
        if not category:
            continue
        row = buckets.setdefault(category, {"category": category, "verified_buyers": 0, "verified_suppliers": 0, "quotes": 0, "deals": 0, "real_transactions": 0, "currencies": set()})
        row["quotes"] += 1
        if price.get("currency"):
            row["currencies"].add(str(price.get("currency")))
    deal_by_id = {str(x.get("id")): x for x in state.get("deals", []) if x.get("id")}
    for txn in state.get("transactions", []):
        if str(txn.get("status") or "") not in {"closed", "settled", "paid", "completed"}:
            continue
        deal = deal_by_id.get(str(txn.get("deal_id") or ""), {})
        category = str(deal.get("need") or "").strip()
        if category:
            row = buckets.setdefault(category, {"category": category, "verified_buyers": 0, "verified_suppliers": 0, "quotes": 0, "deals": 0, "real_transactions": 0, "currencies": set()})
            row["real_transactions"] += 1
    result = []
    for row in buckets.values():
        row["currencies"] = sorted(row["currencies"])
        result.append(row)
    result.sort(key=lambda x: (x["real_transactions"], x["quotes"], x["deals"], x["verified_buyers"] + x["verified_suppliers"]), reverse=True)
    return result[:120]


def _reuse_candidates(state: Dict[str, Any], prices: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for deal in state.get("deals", []):
        if deal.get("source") != "public_evidence":
            continue
        deal_id = str(deal.get("id") or "")
        current = [x for x in state.get("offers", []) if str(x.get("deal_id") or "") == deal_id and x.get("source") != "demo/simulación"]
        if current:
            continue
        category = _norm(deal.get("need"))
        historical = [x for x in prices if _norm(x.get("category")) == category and str(x.get("deal_id") or "") != deal_id]
        if not historical:
            continue
        result.append({
            "deal_id": deal_id,
            "category": deal.get("need"),
            "historical_quote_count": len(historical),
            "suppliers_seen": sorted({str(x.get("supplier")) for x in historical if x.get("supplier")})[:8],
            "evidence_quote_ids": [x.get("quote_id") for x in historical[-8:]],
            "recommended_use": "use_supplier_history_to_prioritize_outreach_not_as_current_price",
        })
    return result[:40]


def enterprise_knowledge_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    graph = _build_graph(state)
    prices = _price_history(state)
    category_memory = _category_memory(state, prices)
    reuse = _reuse_candidates(state, prices)

    company_profiles: List[Dict[str, Any]] = []
    edges = graph.get("edges", [])
    for node in graph.get("nodes", []):
        if node.get("kind") != "company":
            continue
        nid = str(node.get("id"))
        rels = [x for x in edges if x.get("subject") == nid or x.get("object") == nid]
        company_profiles.append({
            "company_node_id": nid,
            "label": node.get("label"),
            "type": (node.get("attrs") or {}).get("type"),
            "relationship_count": len(rels),
            "last_seen_at": node.get("last_seen_at"),
            "verified": (node.get("attrs") or {}).get("verified_company"),
        })
    company_profiles.sort(key=lambda x: x["relationship_count"], reverse=True)

    directive = {
        "updated_at": utcnow(),
        "reuse_candidates": len(reuse),
        "primary_action": "reuse_verified_supplier_history" if reuse else "continue_accumulating_traceable_memory",
        "rule": "historical prices and documents are evidence for prioritization, never silently treated as current commercial terms",
    }
    state["enterprise_knowledge_graph"] = {
        "updated_at": utcnow(),
        "nodes": graph.get("nodes", []),
        "edges": graph.get("edges", []),
        "schema_version": "1.0",
    }
    state["enterprise_knowledge_views"] = {
        "updated_at": utcnow(),
        "supplier_price_history": prices,
        "category_memory": category_memory,
        "company_profiles": company_profiles[:300],
        "reuse_candidates": reuse,
    }
    state["knowledge_graph_directive"] = directive

    if reuse:
        first = reuse[0]
        record_decision(
            state,
            engine="Enterprise Knowledge Graph",
            object_type="deal",
            object_id=str(first.get("deal_id")),
            decision="historical_supplier_memory_available",
            reason=f"Hay {first.get('historical_quote_count')} cotizaciones históricas trazables de la misma categoría; sirven para priorizar proveedores, no como precio vigente.",
            action="research_public",
            confidence=0.9,
            evidence_refs=[str(x) for x in first.get("evidence_quote_ids", [])[:6]],
        )

    return {
        "updated_at": utcnow(),
        "nodes": len(graph.get("nodes", [])),
        "edges": len(graph.get("edges", [])),
        "historical_prices": len(prices),
        "categories": len(category_memory),
        "company_profiles": len(company_profiles),
        "reuse_candidates": len(reuse),
        "directive": directive,
    }
