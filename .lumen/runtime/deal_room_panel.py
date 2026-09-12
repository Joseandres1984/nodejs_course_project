from __future__ import annotations

import html
from typing import Any, Dict, List


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _money(value: Any, currency: str = "USD") -> str:
    if value in (None, ""):
        return "—"
    try:
        return f"{currency} {float(value):,.2f}"
    except (TypeError, ValueError):
        return _esc(value)


def _status_label(status: str) -> str:
    return {
        "human_decision_required": "DECISIÓN HUMANA",
        "close_ready": "LISTO PARA CIERRE",
        "blocked": "BLOQUEADO",
        "active": "ACTIVO",
        "transaction_recorded": "OPERACIÓN REGISTRADA",
    }.get(str(status or ""), str(status or "SIN ESTADO").upper())


def _knowledge_context(state: Dict[str, Any], deal_id: str) -> Dict[str, Any]:
    graph = state.get("enterprise_knowledge_graph", {}) or {}
    nodes = {str(x.get("id")): x for x in graph.get("nodes", []) or [] if x.get("id")}
    target = f"deal:{deal_id}"
    edges = [
        x for x in graph.get("edges", []) or []
        if x.get("subject") == target or x.get("object") == target
    ]
    related_ids = set()
    for edge in edges:
        if edge.get("subject") != target:
            related_ids.add(str(edge.get("subject")))
        if edge.get("object") != target:
            related_ids.add(str(edge.get("object")))
    related = [nodes[x] for x in related_ids if x in nodes]
    return {
        "deal_node": nodes.get(target),
        "edges": edges[:30],
        "related_nodes": related[:30],
    }


def render_deal_room_index(state: Dict[str, Any]) -> str:
    rooms = state.get("deal_rooms", []) or []
    report = state.get("deal_room", {}) or {}
    if not rooms:
        return '''
        <section class="dr-wrap">
          <div class="dr-eyebrow">AUTONOMOUS DEAL ROOM</div>
          <h2>Expedientes comerciales vivos</h2>
          <p>Todavía no hay deals reales materializados para mostrar.</p>
        </section>'''

    cards = ""
    for room in rooms[:8]:
        cfo = ((room.get("economics") or {}).get("cfo") or {})
        next_action = room.get("next_best_action") or {}
        cards += f'''
        <a class="dr-card {_esc(room.get('status'))}" href="/deal-room/{_esc(room.get('deal_id'))}">
          <div class="dr-card-top"><b>{_esc(room.get('deal_id'))}</b><span>{_esc(_status_label(room.get('status')))}</span></div>
          <div class="dr-title">{_esc(room.get('buyer', {}).get('name') or 'Comprador')} · {_esc(room.get('category') or 'sin categoría')}</div>
          <div class="dr-grid-mini">
            <div><small>Readiness</small><b>{_f(room.get('readiness', {}).get('score')):.0f}%</b></div>
            <div><small>Money score</small><b>{_f(cfo.get('money_score')):.0f}</b></div>
            <div><small>Profit</small><b>{_money(cfo.get('company_profit_usd'))}</b></div>
          </div>
          <div class="dr-next"><small>PRÓXIMA ACCIÓN</small><b>{_esc(next_action.get('title') or 'Sin acción')}</b><span>{_esc(next_action.get('owner'))}</span></div>
        </a>'''

    return f'''
    <section class="dr-wrap">
      <div class="dr-top">
        <div><div class="dr-eyebrow">AUTONOMOUS DEAL ROOM</div><h2>Expedientes comerciales vivos</h2><p>Una carpeta única por operación, alimentada por RevOps, CFO, Trade, documentos, Knowledge Graph y controles de cierre.</p></div>
        <div class="dr-stats"><div><small>ROOMS</small><b>{_esc(report.get('rooms', len(rooms)))}</b></div><div><small>JOSÉ</small><b>{_esc(report.get('human_decisions_required', 0))}</b></div><div><small>BLOQUEADOS</small><b>{_esc(report.get('blocked_rooms', 0))}</b></div></div>
      </div>
      <div class="dr-grid">{cards}</div>
    </section>'''


def _fact_rows(data: Dict[str, Any]) -> str:
    return "".join(
        f'<div class="drr-row"><span>{_esc(k.replace("_", " ").title())}</span><b>{_esc(v)}</b></div>'
        for k, v in data.items() if v not in (None, "", [], {})
    ) or '<div class="drr-empty">Sin datos confirmados.</div>'


def _offers(room: Dict[str, Any]) -> str:
    rows = ""
    for offer in room.get("offers", []) or []:
        rows += f'''
        <div class="drr-offer">
          <div><b>{_esc(offer.get('supplier') or offer.get('id'))}</b><small>{_esc(offer.get('id'))}</small></div>
          <div><b>{_money(offer.get('amount'), str(offer.get('currency') or ''))}</b><small>{_esc(offer.get('normalization_status') or '')}</small></div>
          <div><b>{_esc(offer.get('lead_days') or '—')}</b><small>días</small></div>
          <div><b>{_esc(offer.get('incoterm') or '—')}</b><small>Incoterm</small></div>
        </div>'''
    return rows or '<div class="drr-empty">Todavía no hay cotizaciones reales asociadas.</div>'


def _documents(room: Dict[str, Any]) -> str:
    rows = ""
    for doc in room.get("documents", []) or []:
        facts = doc.get("facts") or {}
        rows += f'''
        <div class="drr-doc">
          <div><b>{_esc(doc.get('filename') or doc.get('id'))}</b><small>{_esc(doc.get('document_type'))} · {_esc(doc.get('extraction_status'))}</small></div>
          <div><b>{_money(facts.get('amount'), str(facts.get('currency') or ''))}</b><small>{_esc(facts.get('quote_number') or '')}</small></div>
        </div>'''
    return rows or '<div class="drr-empty">Sin documentos vinculados.</div>'


def _communications(room: Dict[str, Any]) -> str:
    rows = ""
    for msg in (room.get("communications", []) or [])[:12]:
        rows += f'''
        <div class="drr-msg">
          <span class="{_esc(msg.get('direction'))}">{'→' if msg.get('direction') == 'outbound' else '←'}</span>
          <div><b>{_esc(msg.get('subject') or msg.get('kind'))}</b><small>{_esc(msg.get('ts'))} · {_esc(msg.get('status'))}</small></div>
        </div>'''
    return rows or '<div class="drr-empty">Sin comunicaciones asociadas.</div>'


def _decisions(room: Dict[str, Any]) -> str:
    rows = ""
    for row in (room.get("decisions", []) or [])[:12]:
        rows += f'''
        <div class="drr-decision"><div><b>{_esc(row.get('engine'))}</b><small>{_esc(row.get('ts'))}</small></div><div><b>{_esc(row.get('decision'))}</b><small>{_esc(row.get('reason'))}</small></div></div>'''
    return rows or '<div class="drr-empty">Todavía no hay decisiones auditables asociadas al deal.</div>'


def _blockers(room: Dict[str, Any]) -> str:
    rows = ""
    for row in (room.get("risks_and_controls", {}).get("blockers", []) or [])[:15]:
        rows += f'<span class="drr-block {_esc(row.get("severity"))}">{_esc(row.get("source"))}: {_esc(row.get("code"))}</span>'
    return rows or '<span class="drr-ok">Sin bloqueos materiales detectados.</span>'


def _knowledge_html(state: Dict[str, Any], room: Dict[str, Any]) -> str:
    ctx = _knowledge_context(state, str(room.get("deal_id") or ""))
    if not ctx.get("deal_node") and not ctx.get("edges"):
        return '<div class="drr-empty">El Knowledge Graph todavía no materializó relaciones para este deal.</div>'
    rows = ""
    nodes = {str(x.get("id")): x for x in ctx.get("related_nodes", [])}
    for edge in ctx.get("edges", [])[:16]:
        other = edge.get("object") if edge.get("subject") == f"deal:{room.get('deal_id')}" else edge.get("subject")
        node = nodes.get(str(other), {})
        rows += f'<div class="drr-kg"><b>{_esc(edge.get("predicate"))}</b><span>{_esc(node.get("label") or other)}</span><small>conf. {_f(edge.get("confidence"))*100:.0f}%</small></div>'
    return rows


def render_deal_room(room: Dict[str, Any], state: Dict[str, Any]) -> str:
    cfo = ((room.get("economics") or {}).get("cfo") or {})
    next_action = room.get("next_best_action") or {}
    trade = room.get("trade_logistics") or {}
    comparison = trade.get("comparison") or {}
    governance = state.get("master_governance", {}) or {}
    twin = state.get("strategy_simulator", {}) or {}
    active_exp = twin.get("active_experiment") or {}
    recommended = twin.get("recommended_scenario") or {}
    readiness = room.get("readiness") or {}
    close = room.get("risks_and_controls", {}) or {}

    return f'''<!doctype html>
    <html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LUMEN · {_esc(room.get('deal_id'))}</title><style>{detail_css()}</style></head>
    <body><main class="drr-shell">
      <div class="drr-nav"><a href="/command-center">← Command Center</a><span>AUTONOMOUS DEAL ROOM</span></div>
      <header class="drr-hero">
        <div><div class="drr-eyebrow">{_esc(_status_label(room.get('status')))}</div><h1>{_esc(room.get('deal_id'))} · {_esc(room.get('buyer', {}).get('name') or 'Comprador')}</h1><p>{_esc(room.get('category'))} · etapa {_esc(room.get('stage'))}</p></div>
        <div class="drr-score"><small>DEAL READINESS</small><b>{_f(readiness.get('score')):.0f}%</b><span>Cierre {_f(readiness.get('close_readiness_pct')):.0f}%</span></div>
      </header>

      <section class="drr-kpis">
        <div><small>Beneficio</small><b>{_money(cfo.get('company_profit_usd'))}</b></div>
        <div><small>Margen</small><b>{_f(cfo.get('margin_pct')):.1f}%</b></div>
        <div><small>Prob. cierre</small><b>{_f(cfo.get('close_probability'))*100:.0f}%</b></div>
        <div><small>Money Score</small><b>{_f(cfo.get('money_score')):.0f}/100</b></div>
        <div><small>Profit ajustado</small><b>{_money(cfo.get('risk_adjusted_expected_profit_usd'))}</b></div>
      </section>

      <section class="drr-action {'human' if next_action.get('autonomous') is False else ''}"><small>PRÓXIMA MEJOR ACCIÓN · {_esc(next_action.get('owner'))}</small><h2>{_esc(next_action.get('title'))}</h2><p>{_esc(next_action.get('reason'))}</p></section>

      <div class="drr-columns">
        <section class="drr-box"><h3>Comprador</h3>{_fact_rows(room.get('buyer') or {})}</section>
        <section class="drr-box"><h3>Proveedor principal</h3>{_fact_rows(room.get('primary_supplier') or {})}</section>
        <section class="drr-box"><h3>Requerimiento</h3>{_fact_rows(room.get('requirement', {}).get('details') or {})}<div class="drr-note">Confirmado: <b>{'sí' if room.get('requirement', {}).get('confirmed') else 'no'}</b></div></section>
      </div>

      <section class="drr-box wide"><h3>Riesgos y controles</h3><div class="drr-blocks">{_blockers(room)}</div><div class="drr-note">Close gate: {_esc(close.get('close_gate') or 'sin evaluar')} · faltantes: {_esc(', '.join(close.get('preclose_missing') or []) or 'ninguno')}</div></section>

      <div class="drr-columns two">
        <section class="drr-box"><h3>Cotizaciones</h3>{_offers(room)}</section>
        <section class="drr-box"><h3>Trade & Logistics</h3><div class="drr-highlight"><small>Ruta</small><b>{_esc(comparison.get('status') or 'sin comparación')}</b><span>Ahorro landed: {_esc(comparison.get('landed_savings_pct') if comparison.get('landed_savings_pct') is not None else '—')}%</span></div>{_fact_rows(comparison.get('best_international') or comparison.get('best_local') or {})}</section>
      </div>

      <div class="drr-columns two">
        <section class="drr-box"><h3>Documentos</h3>{_documents(room)}</section>
        <section class="drr-box"><h3>Comunicaciones</h3>{_communications(room)}</section>
      </div>

      <div class="drr-columns two">
        <section class="drr-box"><h3>Knowledge Graph</h3>{_knowledge_html(state, room)}</section>
        <section class="drr-box"><h3>Contexto estratégico</h3>
          <div class="drr-row"><span>Company Mode</span><b>{_esc(governance.get('company_mode') or '—')}</b></div>
          <div class="drr-row"><span>Motor dominante</span><b>{_esc(governance.get('winning_engine') or '—')}</b></div>
          <div class="drr-row"><span>Digital Twin</span><b>{_esc(recommended.get('title') or 'sin escenario')}</b></div>
          <div class="drr-row"><span>Experimento</span><b>{_esc(active_exp.get('title') or 'ninguno')}</b></div>
        </section>
      </div>

      <section class="drr-box wide"><h3>Decision Ledger del deal</h3>{_decisions(room)}</section>
      <footer>Deal Room actualizado {_esc(room.get('updated_at'))}. Es un expediente operativo trazable; contratos, órdenes, pagos y términos vinculantes continúan bajo autoridad humana.</footer>
    </main></body></html>'''


def index_css() -> str:
    return '''
    .dr-wrap{margin:12px 0;padding:18px;border:1px solid #28504b;border-radius:19px;background:linear-gradient(135deg,#071817,#0a131c 60%,#0c1520);box-shadow:0 16px 42px #0006}.dr-top{display:flex;justify-content:space-between;gap:18px;align-items:flex-end}.dr-eyebrow{font-size:10px;letter-spacing:.17em;font-weight:900;color:#6ee7c5}.dr-wrap h2{margin:5px 0 4px;font-size:21px}.dr-wrap p{color:#92aaa6;margin:0}.dr-stats{display:flex;gap:6px}.dr-stats>div{min-width:65px;padding:8px;border:1px solid #254c47;border-radius:10px;background:#071312;text-align:center}.dr-stats small{display:block;font-size:8px;color:#688f88}.dr-stats b{font-size:17px}.dr-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:9px;margin-top:14px}.dr-card{display:block;text-decoration:none;color:inherit;border:1px solid #244640;border-radius:13px;padding:12px;background:#081412;transition:.15s}.dr-card:hover{transform:translateY(-1px);border-color:#4ca994}.dr-card.human_decision_required{border-color:#8a6938;background:#19150c}.dr-card.blocked{border-color:#683a3a;background:#170d0d}.dr-card-top{display:flex;justify-content:space-between;gap:9px}.dr-card-top span{font-size:9px;font-weight:900;color:#6ee7c5}.dr-card.human_decision_required .dr-card-top span{color:#f2c36d}.dr-card.blocked .dr-card-top span{color:#ff9696}.dr-title{font-size:12px;color:#9bb5b0;margin:5px 0 8px}.dr-grid-mini{display:grid;grid-template-columns:repeat(3,1fr);gap:5px}.dr-grid-mini>div{background:#06100f;border-radius:8px;padding:6px}.dr-grid-mini small,.dr-next small{display:block;color:#607c76;font-size:8px}.dr-next{margin-top:8px;padding-top:8px;border-top:1px solid #203934}.dr-next b{display:block;font-size:11px}.dr-next span{font-size:9px;color:#6ee7c5}@media(max-width:900px){.dr-top{flex-direction:column;align-items:flex-start}.dr-grid{grid-template-columns:1fr}.dr-stats{width:100%}.dr-stats>div{flex:1}}
    '''


def detail_css() -> str:
    return '''
    :root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#05090d;color:#e7eef1;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.drr-shell{max-width:1180px;margin:0 auto;padding:22px}.drr-nav{display:flex;justify-content:space-between;align-items:center;font-size:10px;letter-spacing:.12em;color:#607a75}.drr-nav a{color:#78dfc5;text-decoration:none}.drr-hero{display:flex;justify-content:space-between;align-items:flex-end;gap:20px;margin-top:18px;padding:22px;border:1px solid #244842;border-radius:20px;background:linear-gradient(135deg,#0c1c1a,#0a111a)}.drr-eyebrow{font-size:10px;letter-spacing:.17em;font-weight:900;color:#73e1c6}.drr-hero h1{margin:5px 0;font-size:30px}.drr-hero p{margin:0;color:#809b96}.drr-score{min-width:150px;text-align:right}.drr-score small{display:block;color:#6d8782}.drr-score b{font-size:36px;color:#76e1c6;display:block}.drr-score span{font-size:10px;color:#8aa29e}.drr-kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-top:10px}.drr-kpis>div{padding:12px;border:1px solid #203833;border-radius:12px;background:#08110f}.drr-kpis small{display:block;color:#627a75;font-size:9px}.drr-kpis b{display:block;margin-top:4px}.drr-action{margin-top:10px;padding:17px;border:1px solid #376a5e;border-radius:15px;background:#0b1b17}.drr-action.human{border-color:#87682f;background:#1a1509}.drr-action small{font-size:9px;color:#6fdabf;letter-spacing:.1em}.drr-action.human small{color:#f0c46b}.drr-action h2{font-size:19px;margin:5px 0}.drr-action p{margin:0;color:#92a9a4}.drr-columns{display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-top:9px}.drr-columns.two{grid-template-columns:1fr 1fr}.drr-box{border:1px solid #1e3430;border-radius:14px;background:#080f0e;padding:14px;min-width:0}.drr-box.wide{margin-top:9px}.drr-box h3{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#82b8ac;margin:0 0 9px}.drr-row{display:flex;justify-content:space-between;gap:12px;border-bottom:1px solid #172824;padding:7px 0;font-size:10px}.drr-row span{color:#607a75}.drr-row b{text-align:right;word-break:break-word}.drr-empty{padding:10px;border:1px dashed #29423d;border-radius:9px;color:#677e79;font-size:10px}.drr-note{font-size:9px;color:#708a84;margin-top:8px}.drr-offer,.drr-doc,.drr-decision{display:grid;grid-template-columns:2fr 1fr 1fr 1fr;gap:8px;padding:8px 0;border-bottom:1px solid #172824;font-size:10px}.drr-doc{grid-template-columns:2fr 1fr}.drr-decision{grid-template-columns:1fr 2fr}.drr-offer small,.drr-doc small,.drr-decision small{display:block;color:#5f7771;margin-top:2px}.drr-msg{display:flex;gap:8px;align-items:flex-start;padding:7px 0;border-bottom:1px solid #172824;font-size:10px}.drr-msg span{width:22px;height:22px;border-radius:50%;display:flex;align-items:center;justify-content:center;background:#0c2720;color:#6ee7c5}.drr-msg span.inbound{background:#151d31;color:#91a7ff}.drr-msg small{display:block;color:#617771;margin-top:2px}.drr-blocks{display:flex;flex-wrap:wrap;gap:5px}.drr-block{font-size:9px;padding:5px 7px;border-radius:99px;border:1px solid #5b4530;color:#e7bd72}.drr-block.high{border-color:#653939;color:#ff9a9a}.drr-block.human{border-color:#6d5731;color:#f0c36c}.drr-ok{font-size:10px;color:#70ddb9}.drr-highlight{padding:10px;border-radius:10px;background:#0c1a17;margin-bottom:8px}.drr-highlight small{display:block;color:#58746d}.drr-highlight b{display:block;margin:3px 0}.drr-highlight span{font-size:10px;color:#74d9bd}.drr-kg{display:grid;grid-template-columns:1fr 1.5fr auto;gap:8px;padding:7px 0;border-bottom:1px solid #172824;font-size:10px}.drr-kg span{color:#a3b6b2}.drr-kg small{color:#5d756f}footer{margin:14px 0 30px;color:#526863;font-size:9px;line-height:1.5}@media(max-width:850px){.drr-shell{padding:12px}.drr-hero{flex-direction:column;align-items:flex-start}.drr-score{text-align:left}.drr-kpis{grid-template-columns:1fr 1fr}.drr-columns,.drr-columns.two{grid-template-columns:1fr}.drr-offer{grid-template-columns:1fr 1fr}.drr-doc,.drr-decision{grid-template-columns:1fr}.drr-hero h1{font-size:23px}}
    '''


def inject_deal_room_index(base_html: str, state: Dict[str, Any]) -> str:
    out = base_html.replace('</head>', '<style>' + index_css() + '</style></head>', 1)
    return out.replace('</body>', render_deal_room_index(state) + '</body>', 1)
