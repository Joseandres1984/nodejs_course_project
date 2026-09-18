from __future__ import annotations

"""LUMEN Command Center 2.0 · Revenue Cockpit.

Read-only owner UI. It separates prepared/accepted/delivered/replied/offer/won/paid truth,
shows First Cash progression, service attribution, acquisition conversion and a persisted
previous-day comparison. It never changes spend, outbound caps or binding authority.
"""

from datetime import datetime
import html
from typing import Any, Dict, List, Tuple

from fastapi import Request
from fastapi.responses import Response

from app import STATE
from outbound_web import app
from cycle_journal import fetch_cycles

VERSION = "2.0-revenue-cockpit"


def _e(v: Any) -> str:
    return html.escape(str(v if v is not None else ""), quote=True)


def _i(v: Any, d: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return d


def _f(v: Any, d: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _money(v: Any) -> str:
    return f"USD {_f(v):,.2f}"


def _list(state: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    value = state.get(key)
    return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []


def _funnel(state: Dict[str, Any]) -> Dict[str, Any]:
    kpis = state.get("business_kpis", {}) or {}
    return kpis.get("funnel", {}) or (state.get("revenue_funnel", {}) or {}).get("counts", {}) or {}


def _real_transactions(state: Dict[str, Any]) -> int:
    good = {"closed", "settled", "paid", "completed", "delivered", "invoiced", "won"}
    return sum(1 for x in _list(state, "transactions") if str(x.get("status") or "").lower() in good and str(x.get("source") or "").lower() != "demo")


def _paid_events(state: Dict[str, Any]) -> int:
    good = {"realized", "realized_partial", "received", "paid", "settled", "completed"}
    return sum(1 for x in _list(state, "revenue_ledger") if str(x.get("status") or "").lower() in good) + sum(1 for x in _list(state, "service_revenue_transactions") if str(x.get("status") or "").lower() in good)


def _actual_rfqs(state: Dict[str, Any]) -> int:
    rows: List[Dict[str, Any]] = []
    for key in ("supplier_rfqs", "supplier_rfq_requests", "rfq_requests"):
        rows.extend(_list(state, key))
    good = {"issued", "sent", "delivered", "quoted", "completed", "active"}
    return sum(1 for x in rows if str(x.get("status") or "").lower() in good)


def _quotes(state: Dict[str, Any]) -> int:
    rows: List[Dict[str, Any]] = []
    for key in ("supplier_quotes", "verified_supplier_quotes", "normalized_quotes"):
        rows.extend(_list(state, key))
    if rows:
        return sum(1 for x in rows if str(x.get("source") or "").lower() != "demo")
    quote = state.get("quote_accelerator", {}) or {}
    for key in ("quotes_received", "verified_quotes", "real_quotes"):
        if quote.get(key) not in (None, ""):
            return _i(quote.get(key))
    return 0


def _service_realized(state: Dict[str, Any]) -> float:
    runtime = state.get("service_revenue_runtime", {}) or {}
    direct = _f(runtime.get("realized_service_revenue_usd"))
    if direct > 0:
        return direct
    total = 0.0
    for x in _list(state, "service_revenue_transactions"):
        if str(x.get("status") or "").lower() in {"paid", "settled", "completed", "received", "realized"}:
            total += max(0.0, _f(x.get("amount_received_usd") or x.get("revenue_usd") or x.get("amount")))
    return total


def _commission_realized(state: Dict[str, Any]) -> float:
    finance = ((state.get("business_kpis", {}) or {}).get("finance", {}) or {})
    return max(0.0, _f(finance.get("realized_profit_usd") or finance.get("realized_company_profit_usd")))


def _services(state: Dict[str, Any]) -> Dict[str, Any]:
    runtime = state.get("service_revenue_runtime", {}) or {}
    pipe = _list(state, "service_sales_pipeline")
    opps = _list(state, "service_revenue_opportunities")
    prepared = sum(1 for x in opps if str(x.get("status") or "") == "prepared_not_sent")
    return {
        "pipeline": _i(runtime.get("pipeline_total"), len(pipe)),
        "prepared": _i(runtime.get("outreach_prepared"), prepared),
        "contacted": _i(runtime.get("real_contacted"), sum(1 for x in pipe if str(x.get("contact_truth") or "") == "provider_accepted")),
        "replies": _i(runtime.get("replies"), sum(1 for x in pipe if str(x.get("stage") or "").lower() == "replied")),
        "proposals": _i(runtime.get("proposal_sent_verified")),
        "won": _i(runtime.get("won"), sum(1 for x in pipe if str(x.get("stage") or "").lower() == "won")),
        "realized": _service_realized(state),
    }


PRODUCTS: List[Tuple[str, str]] = [
    ("SRV-QUOTECHECK", "QuoteCheck"),
    ("SRV-SUPPLIERCHECK", "SupplierCheck"),
    ("SRV-SOURCING-EXPRESS", "Sourcing Express"),
    ("SRV-B2B-PROSPECTING", "B2B Prospecting"),
    ("SRV-EXPORT-SCOUT", "Export Scout"),
    ("SRV-TENDER-HUNTER", "Tender Hunter"),
]


def _service_id(row: Dict[str, Any]) -> str:
    for key in ("service_id", "product_id", "service_code", "product_code", "recommended_service_id"):
        value = str(row.get(key) or "").strip().upper()
        if value:
            return value
    offer = row.get("recommended_offer", {}) or {}
    return str(offer.get("service_id") or offer.get("product_id") or "").strip().upper()


def _product_stats(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    pipe = _list(state, "service_sales_pipeline")
    opps = _list(state, "service_revenue_opportunities")
    intel: List[Dict[str, Any]] = []
    for key in ("intelligence_candidates", "intelligence_service_candidates", "intelligence_revenue_candidates"):
        intel.extend(_list(state, key))
    txs = _list(state, "service_revenue_transactions")
    out = []
    for sid, label in PRODUCTS:
        p = [x for x in pipe if _service_id(x) == sid]
        o = [x for x in opps if _service_id(x) == sid]
        c = [x for x in intel if _service_id(x) == sid]
        tx = [x for x in txs if _service_id(x) == sid]
        out.append({
            "label": label,
            "candidates": len(p) + len(o) + len(c),
            "prepared": sum(1 for x in p + o if str(x.get("stage") or x.get("status") or "").lower() in {"outreach_prepared", "prepared_not_sent", "prepared"}),
            "contacted": sum(1 for x in p if str(x.get("contact_truth") or "").lower() in {"provider_accepted", "contacted_verified"} or str(x.get("stage") or "").lower() == "contacted"),
            "delivered": sum(1 for x in p if x.get("delivery_verified") or x.get("delivered_at")),
            "replies": sum(1 for x in p if str(x.get("contact_truth") or "").lower() in {"replied", "reply_received"} or str(x.get("stage") or "").lower() == "replied"),
            "proposals": sum(1 for x in p if x.get("proposal_sent_verified") or str(x.get("stage") or "").lower() in {"proposal_sent", "proposal_ready"}),
            "won": sum(1 for x in p if str(x.get("stage") or "").lower() == "won"),
            "realized": sum(max(0.0, _f(x.get("amount_received_usd") or x.get("revenue_usd") or x.get("amount"))) for x in tx if str(x.get("status") or "").lower() in {"paid", "settled", "completed", "received", "realized"}),
        })
    return out


def _acquisition(state: Dict[str, Any]) -> Dict[str, Any]:
    events = _list(state, "acquisition_events")
    leads = _list(state, "acquisition_leads")
    clicks = sum(1 for x in events if x.get("event") == "click")
    views = sum(1 for x in events if x.get("event") == "landing_view")
    return {"clicks": clicks, "views": views, "leads": len(leads), "conversion": round(len(leads) / max(1, views) * 100.0, 1)}


def _first_cash(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    sprint = state.get("revenue_sprint_v2", {}) or {}
    focus = list(sprint.get("first_cash_focus_opportunity_ids") or state.get("first_cash_focus_opportunity_ids") or [])[:3]
    opps = {str(x.get("id") or ""): x for x in _list(state, "market_opportunities") if x.get("id")}
    teams = {str(x.get("opportunity_id") or ""): x for x in _list(state, "mission_teams") if x.get("opportunity_id")}
    cases = {str(x.get("first_cash_opportunity_id") or x.get("opportunity_id") or ""): x for x in _list(state, "professional_cases") if x.get("first_cash") or x.get("first_cash_opportunity_id")}
    reqs = {str(x.get("opportunity_id") or ""): x for x in _list(state, "interlocution_cases") if x.get("opportunity_id")}
    accounts = {str(x.get("id") or ""): x for x in _list(state, "candidate_accounts") if x.get("id")}
    out = []
    for oid in focus:
        oid = str(oid); opp = opps.get(oid, {}); team = teams.get(oid, {}); case = cases.get(oid, {}); req_case = reqs.get(oid, {})
        req = req_case.get("requirement", {}) or {}
        buyer = accounts.get(str(opp.get("buyer_account_id") or team.get("buyer_account_id") or ""), {})
        checklist = dict(case.get("first_cash_requirement_checklist", {}) or {})
        for field in ("technical_scope", "quantity", "delivery_location"):
            checklist.setdefault(field, req.get(field) not in (None, "", [], {}))
        missing = [f for f in ("technical_scope", "quantity", "delivery_location") if not checklist.get(f)]
        out.append({
            "id": oid,
            "buyer": team.get("buyer_name") or opp.get("buyer_name") or buyer.get("company_name") or buyer.get("name_hint") or buyer.get("title") or buyer.get("domain") or "Comprador por verificar",
            "category": team.get("category") or opp.get("category") or buyer.get("category") or "—",
            "team": team.get("id") or "sin equipo",
            "stage": team.get("stage") or "—",
            "stagnant": _i(team.get("stagnant_cycles")),
            "case": case.get("id") or "sin caso enlazado",
            "missing": missing,
            "checklist": checklist,
            "evidence": len(req.get("field_evidence", {}) or {}) + len(opp.get("evidence_refs", []) or []),
            "next": case.get("next_action") or team.get("current_task") or req_case.get("next_action") or opp.get("next_action") or "Completar requisito con evidencia exacta",
        })
    return out


def _previous_day() -> Dict[str, Any]:
    rows = (fetch_cycles(page=1, per_page=100).get("rows", []) or [])
    parsed = []
    for row in rows:
        try:
            parsed.append((datetime.strptime(str(row.get("local_time") or ""), "%d/%m/%Y %H:%M:%S"), row))
        except ValueError:
            pass
    if not parsed:
        return {}
    parsed.sort(key=lambda x: x[0], reverse=True)
    today = parsed[0][0].date()
    return next((row for dt, row in parsed if dt.date() < today), {})


def _snapshot(state: Dict[str, Any]) -> Dict[str, Any]:
    funnel = _funnel(state); sprint = state.get("revenue_sprint_v2", {}) or {}; delivery = sprint.get("delivery_truth", {}) or {}
    outbound = state.get("outbound_engine", {}) or {}; brevo = state.get("brevo_delivery_truth", {}) or {}; service = _services(state)
    opportunities = _i(funnel.get("evidence_backed_opportunities") or funnel.get("market_opportunities") or funnel.get("opportunities"), len(_list(state, "market_opportunities")))
    requirements = _i(funnel.get("requirements_ready_for_rfq"), _i((sprint.get("requirement_completion") or {}).get("ready_after")))
    offers = _i(funnel.get("real_offers")); commission = _commission_realized(state); realized = commission + service["realized"]
    real_tx = _real_transactions(state); won = real_tx + service["won"]
    accepted = _i(delivery.get("provider_accepted"), _i(outbound.get("provider_accepted_total") or outbound.get("sent_total")))
    delivered = _i(delivery.get("delivered_verified"), _i(outbound.get("delivered_verified") or brevo.get("delivered_verified_total")))
    replies = _i(delivery.get("replies_detected"), _i(outbound.get("replies_detected")))
    req = sprint.get("requirement_completion", {}) or {}
    bottleneck = (state.get("revenue_funnel", {}) or {}).get("bottleneck", {}) or (state.get("continuous_revenue_drive", {}) or {}).get("bottleneck", {}) or {}
    lane = bottleneck.get("lane") or bottleneck.get("code") or ("requirement_gap" if requirements == 0 and opportunities else "conversion")
    reason = bottleneck.get("reason") or ("Falta completar alcance técnico + cantidad + lugar de entrega con evidencia observada." if requirements == 0 and opportunities else "Avanzar la siguiente etapa comercial verificable.")
    next_action = (state.get("continuous_revenue_drive", {}) or {}).get("primary_action") or (state.get("first_cash_mode", {}) or {}).get("next_action") or "Completar el primer requisito verificable y emitir la primera RFQ real."
    previous = _previous_day(); pc = previous.get("counts", {}) or {}; pm = previous.get("money", {}) or {}
    return {
        "opportunities": opportunities, "requirements": requirements, "rfqs": _actual_rfqs(state), "quotes": _quotes(state), "offers": offers,
        "won": won, "realized": realized, "commission": commission, "service_realized": service["realized"], "prepared": _i(outbound.get("messages_total"), len(_list(state, "outbox"))),
        "accepted": accepted, "delivered": delivered, "replies": replies, "paid_events": _paid_events(state), "service": service,
        "products": _product_stats(state), "acq": _acquisition(state), "first_cash": _first_cash(state),
        "evidence": {"matched": _i(req.get("official_evidence_matched")), "fields": _i(req.get("exact_fields_added")), "docs": _i(req.get("document_cache_total")), "text": _i(req.get("document_text_available"))},
        "action": {"lane": lane, "reason": reason, "next": next_action},
        "yesterday": {"available": bool(previous), "date": str(previous.get("local_time") or "")[:10], "opportunities": _i(pc.get("opportunities")), "requirements": _i(pc.get("requirements_ready")), "offers": _i(pc.get("real_offers")), "won": _i(pc.get("real_transactions")), "realized": _f(pm.get("realized_profit_usd"))},
    }


FIELD_LABELS = {"technical_scope": "alcance", "quantity": "cantidad", "delivery_location": "entrega"}


def _stage(label: str, value: Any, tone: str = "") -> str:
    return f'<div class="rc2-stage {tone}"><span>{_e(label)}</span><b>{_e(value)}</b></div>'


def _delta(now: int, prev: int) -> str:
    value = now - prev
    return f"+{value}" if value > 0 else str(value)


def _render(d: Dict[str, Any]) -> str:
    cash = "COBRADO" if d["realized"] > 0 else "PENDIENTE"; cash_cls = "good" if d["realized"] > 0 else "warn"; acq = d["acq"]; svc = d["service"]; y = d["yesterday"]
    cards = []
    for x in d["first_cash"]:
        miss = ", ".join(FIELD_LABELS.get(v, v) for v in x["missing"]) if x["missing"] else "mínimo RFQ completo"
        checks = "".join(f'<span class="rc2-check {"ok" if x["checklist"].get(k) else "miss"}">{_e(label)} {"✓" if x["checklist"].get(k) else "○"}</span>' for k, label in (("technical_scope", "Alcance"), ("quantity", "Cantidad"), ("delivery_location", "Entrega")))
        cards.append(f'<article class="rc2-focus"><div class="rc2-focushead"><b>{_e(x["id"])}</b><span>{_e(x["stage"])}</span></div><h3>{_e(x["buyer"])}</h3><div class="rc2-muted">{_e(x["category"])}</div><div class="rc2-checks">{checks}</div><div class="rc2-row"><span>Falta</span><strong>{_e(miss)}</strong></div><div class="rc2-row"><span>Caso</span><strong>{_e(x["case"])}</strong></div><div class="rc2-row"><span>Equipo</span><strong>{_e(x["team"])}</strong></div><div class="rc2-row"><span>Ciclos sin avance</span><strong>{x["stagnant"]}</strong></div><div class="rc2-row"><span>Evidencias vinculadas</span><strong>{x["evidence"]}</strong></div><div class="rc2-next">{_e(x["next"])}</div></article>')
    first_cash = "".join(cards) or '<div class="rc2-empty">Esperando selección First Cash persistida.</div>'
    products = "".join(f'<tr><td><b>{_e(x["label"])}</b></td><td>{x["candidates"]}</td><td>{x["prepared"]}</td><td>{x["contacted"]}</td><td>{x["delivered"]}</td><td>{x["replies"]}</td><td>{x["proposals"]}</td><td>{x["won"]}</td><td>{_money(x["realized"])}</td></tr>' for x in d["products"])
    if y["available"]:
        compare = f'<div class="rc2-comparegrid"><div><span>Oportunidades</span><b>{d["opportunities"]}</b><small>{_delta(d["opportunities"], y["opportunities"])} vs ayer</small></div><div><span>Requisitos RFQ</span><b>{d["requirements"]}</b><small>{_delta(d["requirements"], y["requirements"])} vs ayer</small></div><div><span>Ofertas reales</span><b>{d["offers"]}</b><small>{_delta(d["offers"], y["offers"])} vs ayer</small></div><div><span>Ventas reales</span><b>{d["won"]}</b><small>{_delta(d["won"], y["won"])} vs ayer</small></div></div><div class="rc2-muted">Base persistida de ayer: {_e(y["date"])} · beneficio realizado registrado: {_money(y["realized"])}</div>'
    else:
        compare = '<div class="rc2-empty">Todavía no hay una base persistida de un día anterior para comparar. No se inventan deltas.</div>'
    return f'''<section class="rc2" id="lumen-revenue-cockpit-v2">
<div class="rc2-header"><div><div class="rc2-eye">LUMEN · COMMAND CENTER 2.0</div><h1>Revenue Cockpit</h1><p>Una sola verdad comercial: preparado ≠ aceptado ≠ entregado ≠ respondido ≠ oferta ≠ ganado ≠ cobrado.</p></div><div class="rc2-cash {cash_cls}"><span>PRIMER COBRO</span><b>{cash}</b><small>{_money(d["realized"])}</small></div></div>
<div class="rc2-truth">{_stage("Realizado verificado", _money(d["realized"]), "good" if d["realized"] else "")}{_stage("Ventas ganadas", d["won"])}{_stage("Ofertas reales", d["offers"])}{_stage("Respuestas", d["replies"])}{_stage("Entregados verificados", d["delivered"], "good" if d["delivered"] else "")}{_stage("Aceptados proveedor", d["accepted"])}{_stage("Requisitos listos RFQ", d["requirements"], "warn" if d["requirements"] == 0 else "good")}</div>
<div class="rc2-grid2"><div class="rc2-card"><div class="rc2-label">FIRST CASH · EMBUDO REAL</div><div class="rc2-funnel">{_stage("Oportunidades", d["opportunities"])}{_stage("Requisito completo", d["requirements"])}{_stage("RFQ emitida", d["rfqs"])}{_stage("Cotizaciones", d["quotes"])}{_stage("Oferta real", d["offers"])}{_stage("Venta", d["won"])}{_stage("Cobro", _money(d["realized"]))}</div><div class="rc2-evidence">Evidencia procurement: {d["evidence"]["matched"]} matches · {d["evidence"]["fields"]} campos exactos agregados · {d["evidence"]["text"]}/{d["evidence"]["docs"]} documentos con texto.</div></div><div class="rc2-card rc2-action"><div class="rc2-label">QUÉ TIENE QUE HACER LUMEN AHORA</div><div class="rc2-bottleneck">{_e(d["action"]["lane"])}</div><p>{_e(d["action"]["reason"])}</p><div class="rc2-next big">{_e(d["action"]["next"])}</div><small>Sin aumentar gasto, cupos de envío ni autoridad vinculante.</small></div></div>
<div class="rc2-card"><div class="rc2-sectionhead"><div><div class="rc2-label">FIRST CASH · 3 PRIORIDADES</div><h2>Del equipo a la acción verificable</h2></div><span>caso → requisito → RFQ</span></div><div class="rc2-focusgrid">{first_cash}</div></div>
<div class="rc2-grid2"><div class="rc2-card"><div class="rc2-label">SEMÁFORO DE VERDAD COMERCIAL</div><div class="rc2-semaphore">{_stage("Preparado / generado", d["prepared"])}{_stage("Aceptado por proveedor", d["accepted"])}{_stage("Entregado", d["delivered"])}{_stage("Respondió", d["replies"])}{_stage("Oferta", d["offers"])}{_stage("Ganado", d["won"])}{_stage("Cobrado", d["paid_events"], "good" if d["paid_events"] else "")}</div><div class="rc2-muted">Aceptación y entrega permanecen separadas: cada etapa exige evidencia propia.</div></div><div class="rc2-card"><div class="rc2-label">CAPTACIÓN</div><div class="rc2-acq">{_stage("Clicks", acq["clicks"])}{_stage("Landing views", acq["views"])}{_stage("Leads", acq["leads"])}{_stage("Conversión", f'{acq["conversion"]:.1f}%')}</div><a class="rc2-link" href="/acquisition">Abrir captación →</a></div></div>
<div class="rc2-card"><div class="rc2-sectionhead"><div><div class="rc2-label">SERVICIOS LUMEN</div><h2>Producto por producto</h2></div><span>pipeline {svc["pipeline"]} · preparados {svc["prepared"]} · contactados reales {svc["contacted"]} · respuestas {svc["replies"]} · ganados {svc["won"]}</span></div><div class="rc2-tablewrap"><table><thead><tr><th>Servicio</th><th>Candidatos</th><th>Preparados</th><th>Contactados</th><th>Entregados</th><th>Respuestas</th><th>Propuestas</th><th>Ganados</th><th>Realizado</th></tr></thead><tbody>{products}</tbody></table></div><div class="rc2-muted">Los ceros por producto indican que no existe una fila persistida atribuida a ese producto; no se reparte actividad global por estimación.</div></div>
<div class="rc2-card"><div class="rc2-sectionhead"><div><div class="rc2-label">AYER VS HOY</div><h2>¿LUMEN movió una etapa comercial?</h2></div><span>historial persistente</span></div>{compare}</div>
<div class="rc2-splitmoney"><span>Operaciones/comisiones realizadas: <b>{_money(d["commission"])}</b></span><span>Servicios realizados: <b>{_money(d["service_realized"])}</b></span></div><div class="rc2-below">↓ Debajo continúa el Command Center operativo completo: salud técnica, agentes, búsquedas, documentos, Instagram, distribución y controles.</div></section>'''


CSS = '''<style id="lumen-revenue-cockpit-v2-css">
.rc2{max-width:1480px;margin:0 auto 14px;padding:18px;color:#eef7fb;font-family:Inter,ui-sans-serif,system-ui,-apple-system}.rc2 *{box-sizing:border-box}.rc2-header{display:flex;align-items:flex-end;justify-content:space-between;gap:18px;padding:18px;border:1px solid #31536a;border-radius:20px;background:radial-gradient(circle at 0 0,#17384b,#08151e 54%);box-shadow:0 16px 42px #0007}.rc2-eye,.rc2-label{font-size:10px;font-weight:950;letter-spacing:.16em;text-transform:uppercase;color:#8bd8ff}.rc2 h1{font-size:34px;line-height:1;margin:6px 0}.rc2 h2{font-size:18px;margin:5px 0}.rc2 h3{font-size:15px;margin:9px 0 3px}.rc2-header p{color:#95aebb;margin:0;line-height:1.45}.rc2-cash{min-width:190px;border:1px solid #725e28;border-radius:15px;padding:13px 15px;background:#1b1708}.rc2-cash.good{border-color:#2e7550;background:#0b2418}.rc2-cash span,.rc2-cash b,.rc2-cash small{display:block}.rc2-cash span{font-size:9px;color:#9fb0a1;letter-spacing:.12em}.rc2-cash b{font-size:21px;margin:3px 0;color:#ffd36a}.rc2-cash.good b{color:#7ce7b3}.rc2-cash small{color:#c8d3d8}.rc2-truth{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:8px;margin:10px 0}.rc2-stage{border:1px solid #213e4e;border-radius:12px;background:#081821;padding:10px;min-width:0}.rc2-stage span,.rc2-stage b{display:block}.rc2-stage span{font-size:9px;text-transform:uppercase;letter-spacing:.08em;color:#7895a5}.rc2-stage b{font-size:19px;margin-top:4px;overflow-wrap:anywhere}.rc2-stage.good b{color:#7ce7b3}.rc2-stage.warn b{color:#ffd36a}.rc2-grid2{display:grid;grid-template-columns:1.35fr .65fr;gap:10px;margin:10px 0}.rc2-card{border:1px solid #1e4052;border-radius:17px;background:linear-gradient(180deg,#0c1d28,#08151e);padding:15px;margin:10px 0;box-shadow:0 11px 28px #0004}.rc2-grid2>.rc2-card{margin:0}.rc2-funnel,.rc2-semaphore,.rc2-acq{display:grid;gap:7px;margin-top:12px}.rc2-funnel,.rc2-semaphore{grid-template-columns:repeat(7,minmax(0,1fr))}.rc2-acq{grid-template-columns:repeat(4,minmax(0,1fr))}.rc2-evidence,.rc2-muted{font-size:10px;color:#7e98a7;line-height:1.5;margin-top:9px}.rc2-action p{color:#a9bec9;line-height:1.5}.rc2-bottleneck{font-size:24px;font-weight:950;color:#ffd36a;margin-top:8px}.rc2-next{margin-top:10px;border-left:3px solid #d7ff64;background:#0c2417;padding:9px 10px;border-radius:0 9px 9px 0;color:#dceadf;font-size:11px;line-height:1.45}.rc2-next.big{font-size:13px;font-weight:800}.rc2-sectionhead{display:flex;justify-content:space-between;align-items:flex-end;gap:10px}.rc2-sectionhead>span{font-size:10px;color:#839caa;text-align:right}.rc2-focusgrid{display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-top:12px}.rc2-focus{border:1px solid #28495a;border-radius:13px;background:#07161f;padding:12px}.rc2-focushead{display:flex;justify-content:space-between;gap:8px}.rc2-focushead b{color:#d7ff64}.rc2-focushead span{font-size:10px;color:#8bd8ff}.rc2-checks{display:flex;gap:5px;flex-wrap:wrap;margin:9px 0}.rc2-check{font-size:9px;border-radius:999px;padding:4px 7px;border:1px solid #34505c}.rc2-check.ok{color:#7ce7b3;border-color:#2f694b}.rc2-check.miss{color:#ffd36a;border-color:#735f2b}.rc2-row{display:flex;justify-content:space-between;gap:12px;border-top:1px solid #173442;padding:7px 0;font-size:10px}.rc2-row span{color:#7893a2}.rc2-row strong{text-align:right;overflow-wrap:anywhere}.rc2-conv{display:flex;align-items:baseline;gap:8px;margin-top:10px}.rc2-link{display:inline-block;margin-top:10px;color:#8bd8ff!important;text-decoration:none;font-weight:850}.rc2-tablewrap{overflow:auto;margin-top:10px}.rc2 table{width:100%;border-collapse:collapse;min-width:880px}.rc2 th,.rc2 td{padding:8px 7px;border-bottom:1px solid #173442;text-align:right;font-size:10px;white-space:nowrap}.rc2 th:first-child,.rc2 td:first-child{text-align:left}.rc2 th{color:#7894a3;text-transform:uppercase;font-size:8px;letter-spacing:.07em}.rc2 td:last-child{color:#7ce7b3}.rc2-comparegrid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:10px}.rc2-comparegrid>div{border:1px solid #234353;border-radius:11px;background:#071720;padding:10px}.rc2-comparegrid span,.rc2-comparegrid b,.rc2-comparegrid small{display:block}.rc2-comparegrid span{font-size:9px;color:#7894a4;text-transform:uppercase}.rc2-comparegrid b{font-size:22px;margin-top:4px}.rc2-comparegrid small{color:#9db1bb;margin-top:3px}.rc2-empty{border:1px dashed #315064;border-radius:11px;padding:15px;color:#8ca5b3;margin-top:10px}.rc2-splitmoney{display:flex;gap:8px;flex-wrap:wrap}.rc2-splitmoney span{border:1px solid #254657;border-radius:999px;background:#081821;padding:7px 10px;font-size:10px}.rc2-below{text-align:center;color:#627f90;font-size:10px;margin:12px 0 2px}@media(max-width:1100px){.rc2-truth{grid-template-columns:repeat(4,1fr)}.rc2-funnel,.rc2-semaphore{grid-template-columns:repeat(4,1fr)}.rc2-grid2{grid-template-columns:1fr}}@media(max-width:760px){.rc2{padding:10px}.rc2-header{align-items:flex-start;flex-direction:column}.rc2-cash{width:100%}.rc2-truth{grid-template-columns:1fr 1fr}.rc2-funnel,.rc2-semaphore,.rc2-acq{grid-template-columns:1fr 1fr}.rc2-focusgrid{grid-template-columns:1fr}.rc2-comparegrid{grid-template-columns:1fr 1fr}.rc2 h1{font-size:28px}.rc2-stage b{font-size:17px}.rc2-sectionhead{align-items:flex-start;flex-direction:column}.rc2-sectionhead>span{text-align:left}}
</style>'''


def inject_revenue_cockpit(page: str, state: Dict[str, Any]) -> str:
    if "lumen-revenue-cockpit-v2-css" not in page:
        page = page.replace("</head>", CSS + "</head>", 1)
    if "lumen-revenue-cockpit-v2" in page:
        return page
    return page.replace("<body>", "<body>" + _render(_snapshot(state)), 1)


@app.middleware("http")
async def revenue_cockpit_injector(request: Request, call_next):
    response = await call_next(request)
    if request.url.path != "/command-center" or "text/html" not in str(response.headers.get("content-type") or ""):
        return response
    try:
        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        text = inject_revenue_cockpit(body.decode("utf-8", errors="replace"), STATE)
        headers = dict(response.headers); headers.pop("content-length", None)
        print({"revenue_cockpit_v2": {"version": VERSION, "status": "applied", "visible": "lumen-revenue-cockpit-v2" in text, "truth_stages_separated": True, "spend_changed": False, "outbound_caps_changed": False, "authority_changed": False}}, flush=True)
        return Response(content=text, status_code=response.status_code, headers=headers, media_type="text/html")
    except Exception as exc:
        print({"revenue_cockpit_v2": {"status": "error", "error": f"{type(exc).__name__}: {str(exc)[:220]}"}}, flush=True)
        return response


print({"command_center_revenue_v2_runtime": {"version": VERSION, "status": "installed", "route": "/command-center", "mobile_first": True, "persistent_day_comparison": True, "spend_changed": False, "outbound_caps_changed": False, "binding_authority_changed": False}}, flush=True)
