from __future__ import annotations

import os
from typing import Any, Dict, List

from autonomy_governor import record_decision
from scout_connector import API_KEY, PROVIDER, DAILY_QUERY_BUDGET, _budget, _store_results, search, utcnow


MIN_ATTACK_PRIORITY = float(os.getenv("LUMEN_DEEP_DIVE_MIN_PRIORITY", "78"))
MAX_ACTIVE_CASES = max(1, min(5, int(os.getenv("LUMEN_DEEP_DIVE_MAX_CASES", "3"))))
MAX_QUERIES_PER_TICK = max(1, min(3, int(os.getenv("LUMEN_DEEP_DIVE_MAX_QUERIES", "1"))))
TARGET_SUPPLIER_ALTERNATIVES = max(2, min(7, int(os.getenv("LUMEN_DEEP_DIVE_TARGET_SUPPLIERS", "4"))))


def _norm(value: Any) -> str:
    return " ".join(str(value or "").lower().strip().split())


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _log(state: Dict[str, Any], message: str) -> None:
    state.setdefault("activity", []).insert(0, {"ts": utcnow(), "msg": message})
    state["activity"] = state["activity"][:100]


def _account_map(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(x.get("id")): x for x in state.get("candidate_accounts", []) if x.get("id")}


def _supplier_pool(state: Dict[str, Any], category: Any) -> List[Dict[str, Any]]:
    target = _norm(category)
    suppliers = [
        x for x in state.get("candidate_accounts", [])
        if x.get("type") == "supplier" and x.get("verified_company") and _norm(x.get("category")) == target
    ]
    suppliers.sort(
        key=lambda x: (
            _f(x.get("verification_score")),
            1 if x.get("commercial_channel_verified") else 0,
            _f(x.get("lead_score")),
        ),
        reverse=True,
    )
    return suppliers


def _opportunity_priority(opp: Dict[str, Any]) -> float:
    return _f(opp.get("portfolio_priority_score"), _f(opp.get("score")))


def _eligible_opportunities(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    opportunities = [
        x for x in state.get("market_opportunities", [])
        if x.get("source") == "public_evidence" and x.get("buyer_company_verified") and x.get("supplier_company_verified")
    ]
    opportunities.sort(key=_opportunity_priority, reverse=True)
    if not opportunities:
        return []
    strong = [x for x in opportunities if _opportunity_priority(x) >= MIN_ATTACK_PRIORITY]
    # Always keep the best real opportunity under observation, even before it reaches attack threshold.
    return (strong or opportunities[:1])[:MAX_ACTIVE_CASES]


def _requirement_case(state: Dict[str, Any], opportunity_id: str) -> Dict[str, Any]:
    return next(
        (x for x in state.get("interlocution_cases", []) if str(x.get("opportunity_id") or "") == opportunity_id),
        {},
    )


def _deep_dive_evidence_query(buyer: Dict[str, Any], category: str) -> str | None:
    domain = str(buyer.get("domain") or "").strip()
    if not domain:
        return None
    return (
        f'site:{domain} "{category}" '
        '(compras OR abastecimiento OR procurement OR proveedores OR licitación OR licitacion OR cotización OR cotizacion OR pliego)'
    )


def _supplier_expansion_query(category: str) -> str:
    return f'"{category}" fabricante distribuidor proveedor Argentina stock industrial'


def _win_score(opp: Dict[str, Any], buyer: Dict[str, Any], suppliers: List[Dict[str, Any]], requirement_ready: bool) -> float:
    evidence = min(100.0, _f(opp.get("score")))
    learned = min(100.0, _f(opp.get("learned_category_score"), 50.0))
    demand = min(100.0, _f(buyer.get("demand_score")))
    contact = 100.0 if buyer.get("commercial_channel_verified") else 25.0
    supplier_depth = min(100.0, len(suppliers) / max(1, TARGET_SUPPLIER_ALTERNATIVES) * 100.0)
    requirement = 100.0 if requirement_ready else 20.0
    return round(
        evidence * 0.28
        + learned * 0.14
        + demand * 0.20
        + contact * 0.10
        + supplier_depth * 0.13
        + requirement * 0.15,
        2,
    )


def _gaps(opp: Dict[str, Any], buyer: Dict[str, Any], suppliers: List[Dict[str, Any]], requirement_case: Dict[str, Any]) -> List[str]:
    gaps: List[str] = []
    if not buyer.get("demand_signal"):
        gaps.append("demanda_no_confirmada")
    if not buyer.get("commercial_channel_verified"):
        gaps.append("canal_comprador_no_verificado")
    if not requirement_case.get("supplier_rfq_ready"):
        gaps.append("requerimiento_no_completo")
    if len(suppliers) < TARGET_SUPPLIER_ALTERNATIVES:
        gaps.append("pocas_alternativas_de_proveedor")
    if not any(x.get("commercial_channel_verified") for x in suppliers):
        gaps.append("proveedores_sin_canal_comercial_verificado")
    if not opp.get("requirement_confirmed"):
        gaps.append("condiciones_reales_aun_no_confirmadas")
    if opp.get("economic_value") in (None, 0, ""):
        gaps.append("valor_economico_real_desconocido")
    return list(dict.fromkeys(gaps))


def _strategy(gaps: List[str], supplier_count: int, win_score: float) -> Dict[str, Any]:
    actions: List[Dict[str, Any]] = []

    def add(priority: int, code: str, objective: str, autonomous: bool = True) -> None:
        actions.append({"priority": priority, "code": code, "objective": objective, "autonomous": autonomous})

    if "demanda_no_confirmada" in gaps:
        add(100, "prove_demand", "Profundizar evidencia de necesidad antes de invertir esfuerzo comercial adicional")
    if "requerimiento_no_completo" in gaps or "condiciones_reales_aun_no_confirmadas" in gaps:
        add(98, "confirm_requirement", "Obtener especificación, cantidad, entrega y condiciones comerciales reales del comprador")
    if "canal_comprador_no_verificado" in gaps:
        add(94, "unlock_buyer_channel", "Localizar exclusivamente un canal corporativo público y verificable del comprador")
    if "pocas_alternativas_de_proveedor" in gaps:
        add(92, "expand_supplier_pool", f"Elevar el pool hasta al menos {TARGET_SUPPLIER_ALTERNATIVES} proveedores verificables")
    if "proveedores_sin_canal_comercial_verificado" in gaps:
        add(90, "unlock_supplier_channels", "Verificar canales comerciales corporativos de los proveedores mejor puntuados")
    if "valor_economico_real_desconocido" in gaps:
        add(88, "price_discovery", "Conseguir ofertas comparables antes de definir margen o propuesta")

    if supplier_count >= TARGET_SUPPLIER_ALTERNATIVES:
        add(84, "supplier_competition", "Mantener competencia entre proveedores por precio, plazo, pago, garantía y documentación")
    if not gaps and win_score >= 80:
        add(86, "accelerate", "Acelerar propuesta y negociación sin conceder margen innecesariamente")

    actions.sort(key=lambda x: x["priority"], reverse=True)
    return {
        "attack_mode": win_score >= 75,
        "primary_action": actions[0] if actions else {"priority": 70, "code": "observe", "objective": "Mantener seguimiento", "autonomous": True},
        "actions": actions[:6],
        "negotiation_doctrine": [
            "no depender de un único proveedor cuando existan alternativas verificables",
            "comparar costo total, plazo, forma de pago, garantía, documentación y riesgo, no solo precio unitario",
            "no revelar el margen interno ni la mejor alternativa disponible a la contraparte",
            "usar competencia entre alternativas para mejorar condiciones sin inventar ofertas ni presionar con información falsa",
            "escalar contrato, compra, pago o aceptación vinculante para aprobación humana",
        ],
    }


def _upsert_case(state: Dict[str, Any], opp: Dict[str, Any], account_by_id: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    cases = state.setdefault("deep_dive_cases", [])
    opportunity_id = str(opp.get("id") or "")
    existing = next((x for x in cases if str(x.get("opportunity_id") or "") == opportunity_id), None)
    buyer = account_by_id.get(str(opp.get("buyer_account_id") or ""), {})
    supplier = account_by_id.get(str(opp.get("supplier_account_id") or ""), {})
    suppliers = _supplier_pool(state, opp.get("category"))
    req_case = _requirement_case(state, opportunity_id)
    requirement_ready = bool(req_case.get("supplier_rfq_ready"))
    win_score = _win_score(opp, buyer, suppliers, requirement_ready)
    gaps = _gaps(opp, buyer, suppliers, req_case)
    strategy = _strategy(gaps, len(suppliers), win_score)

    dossier = existing or {
        "id": f"DIVE-{len(cases)+1:05d}",
        "opportunity_id": opportunity_id,
        "created_at": utcnow(),
        "cycles": 0,
        "research_evidence": [],
        "research_queries": [],
    }
    if existing is None:
        cases.append(dossier)

    dossier["cycles"] = int(dossier.get("cycles") or 0) + 1
    dossier.update({
        "updated_at": utcnow(),
        "category": opp.get("category"),
        "portfolio_priority_score": round(_opportunity_priority(opp), 2),
        "win_score": win_score,
        "status": "attack" if strategy["attack_mode"] else "watch",
        "buyer_account_id": buyer.get("id"),
        "buyer_name": buyer.get("company_name") or buyer.get("name_hint") or buyer.get("domain"),
        "buyer_domain": buyer.get("domain"),
        "buyer_demand_score": _f(buyer.get("demand_score")),
        "buyer_channel_verified": bool(buyer.get("commercial_channel_verified")),
        "selected_supplier_account_id": supplier.get("id"),
        "selected_supplier_name": supplier.get("company_name") or supplier.get("name_hint") or supplier.get("domain"),
        "supplier_alternative_count": len(suppliers),
        "supplier_alternatives": [
            {
                "id": x.get("id"),
                "name": x.get("company_name") or x.get("name_hint") or x.get("domain"),
                "domain": x.get("domain"),
                "verification_score": x.get("verification_score"),
                "commercial_channel_verified": bool(x.get("commercial_channel_verified")),
            }
            for x in suppliers[:TARGET_SUPPLIER_ALTERNATIVES + 2]
        ],
        "requirement_ready": requirement_ready,
        "requirement_completeness": req_case.get("requirement_completeness", 0),
        "gaps": gaps,
        "strategy": strategy,
        "next_action": strategy["primary_action"].get("objective"),
        "evidence_refs": list(dict.fromkeys([
            *[str(x) for x in opp.get("evidence_refs", [])],
            *[str(x) for x in buyer.get("demand_evidence_urls", [])],
            *[str(x) for x in buyer.get("commercial_contact_evidence", [])],
            *[str(x) for x in supplier.get("commercial_contact_evidence", [])],
        ]))[:12],
    })
    opp["deep_dive_case_id"] = dossier["id"]
    opp["deep_dive_win_score"] = win_score
    opp["deep_dive_status"] = dossier["status"]
    return dossier


def _research_case(state: Dict[str, Any], dossier: Dict[str, Any], account_by_id: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
    stats = {"queries": 0, "new_supplier_leads": 0, "new_evidence": 0, "errors": 0}
    if not (PROVIDER and API_KEY):
        return stats

    budget = _budget(state)
    remaining = int(budget.get("queries_remaining") or 0)
    if remaining <= 0:
        return stats

    buyer = account_by_id.get(str(dossier.get("buyer_account_id") or ""), {})
    category = str(dossier.get("category") or "").strip()
    queries: List[tuple[str, str]] = []

    # First close the supplier-depth gap; then spend research on the buyer's official-domain evidence.
    if dossier.get("supplier_alternative_count", 0) < TARGET_SUPPLIER_ALTERNATIVES and category:
        queries.append(("supplier_expansion", _supplier_expansion_query(category)))
    buyer_query = _deep_dive_evidence_query(buyer, category)
    if buyer_query:
        queries.append(("buyer_official_evidence", buyer_query))

    seen_queries = set(str(x) for x in dossier.setdefault("research_queries", []))
    allowed = min(MAX_QUERIES_PER_TICK, remaining)
    for kind, query in [x for x in queries if x[1] not in seen_queries][:allowed]:
        try:
            budget["queries_used"] = int(budget.get("queries_used") or 0) + 1
            stats["queries"] += 1
            results = search(query)
            dossier["research_queries"].append(query)
            if kind == "supplier_expansion":
                created = _store_results(state, query, "supplier", category, results)
                stats["new_supplier_leads"] += created
                _log(state, f"Deep Dive amplió proveedores para {dossier['id']}: {created} candidatos nuevos para verificar.")
            else:
                existing_urls = {str(x.get("url")) for x in dossier.setdefault("research_evidence", [])}
                for item in results[:5]:
                    url = str(item.get("url") or "")
                    if not url or url in existing_urls:
                        continue
                    dossier["research_evidence"].append({
                        "kind": kind,
                        "url": url,
                        "title": str(item.get("title") or "")[:300],
                        "snippet": str(item.get("snippet") or "")[:600],
                        "created_at": utcnow(),
                    })
                    existing_urls.add(url)
                    stats["new_evidence"] += 1
                dossier["research_evidence"] = dossier["research_evidence"][-30:]
        except Exception as exc:
            stats["errors"] += 1
            dossier["last_research_error"] = str(exc)[:180]

    budget["queries_remaining"] = max(0, DAILY_QUERY_BUDGET - int(budget.get("queries_used") or 0))
    budget["updated_at"] = utcnow()
    budget["last_deep_dive_case"] = dossier.get("id")
    return stats


def deep_dive_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    account_by_id = _account_map(state)
    eligible = _eligible_opportunities(state)
    active: List[Dict[str, Any]] = []
    for opp in eligible:
        active.append(_upsert_case(state, opp, account_by_id))

    active.sort(key=lambda x: (x.get("status") == "attack", _f(x.get("win_score")), _f(x.get("portfolio_priority_score"))), reverse=True)
    research = {"queries": 0, "new_supplier_leads": 0, "new_evidence": 0, "errors": 0}
    if active:
        research = _research_case(state, active[0], account_by_id)

    primary = active[0] if active else None
    report = {
        "updated_at": utcnow(),
        "mode": "opportunity_deep_dive",
        "active_cases": len(active),
        "attack_cases": sum(1 for x in active if x.get("status") == "attack"),
        "primary_case_id": primary.get("id") if primary else None,
        "primary_opportunity_id": primary.get("opportunity_id") if primary else None,
        "primary_win_score": primary.get("win_score") if primary else None,
        "primary_next_action": primary.get("next_action") if primary else None,
        "research": research,
        "cases": [
            {
                "id": x.get("id"),
                "opportunity_id": x.get("opportunity_id"),
                "category": x.get("category"),
                "status": x.get("status"),
                "win_score": x.get("win_score"),
                "supplier_alternative_count": x.get("supplier_alternative_count"),
                "gaps": x.get("gaps"),
                "next_action": x.get("next_action"),
            }
            for x in active
        ],
    }
    state["opportunity_deep_dive"] = report

    if primary:
        record_decision(
            state,
            engine="Opportunity Deep Dive",
            object_type="market_opportunity",
            object_id=str(primary.get("opportunity_id") or ""),
            decision="attack" if primary.get("status") == "attack" else "watch",
            reason=(
                f"Win score {float(primary.get('win_score') or 0):.1f}; "
                f"{int(primary.get('supplier_alternative_count') or 0)} proveedores alternativos; "
                f"próximo paso: {primary.get('next_action')}"
            ),
            action="score_opportunity",
            confidence=min(0.98, max(0.35, _f(primary.get("win_score")) / 100.0)),
            evidence_refs=list(primary.get("evidence_refs") or [])[:8],
        )
        _log(
            state,
            f"Opportunity Deep Dive priorizó {primary.get('opportunity_id')} con win score {float(primary.get('win_score') or 0):.1f}: {primary.get('next_action')}",
        )

    # Bound persisted cases while preserving the strongest/recently active dossiers.
    cases = state.setdefault("deep_dive_cases", [])
    if len(cases) > 100:
        active_ids = {x.get("id") for x in active}
        ordered = sorted(
            cases,
            key=lambda x: (x.get("id") in active_ids, _f(x.get("win_score")), str(x.get("updated_at") or "")),
            reverse=True,
        )
        state["deep_dive_cases"] = ordered[:100]

    return report
