from __future__ import annotations

import html
from typing import Any, Dict


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _network_section(state: Dict[str, Any]) -> str:
    report = state.get("supplier_network", {}) or {}
    profiles = state.get("supplier_network_profiles", []) or []
    squads = state.get("supplier_squads", []) or []
    directive = report.get("primary_directive", {}) or {}
    if not report:
        return '<section class="sn-wrap"><div class="sn-eye">PROCUREMENT · SUPPLIER NETWORK</div><h2>Esperando primer ciclo de procurement</h2></section>'

    suppliers = ""
    for row in profiles[:6]:
        qm = row.get("quote_metrics", {}) or {}
        suppliers += f'''
        <div class="sn-card">
          <div class="sn-head"><b>{_esc(row.get('supplier'))}</b><span>{_esc(row.get('tier'))}</span></div>
          <div class="sn-score">{_f(row.get('network_score')):.0f}<small>/100</small></div>
          <div class="sn-meta">conf. {_f(row.get('confidence'))*100:.0f}% · {_esc(row.get('market') or 'mercado s/d')}</div>
          <div class="sn-mini">Cotizaciones {qm.get('quotes',0)} · comparables {qm.get('comparable_quotes',0)} · resp. {_f((row.get('response_metrics') or {}).get('shrunk_response_rate'))*100:.0f}%</div>
        </div>'''

    squad_rows = ""
    for squad in squads[:6]:
        members = squad.get("squad", []) or []
        chips = "".join(f'<span>{_esc(x.get("role"))}: {_esc(x.get("supplier"))}</span>' for x in members)
        squad_rows += f'''
        <a class="sn-squad" href="/deal-room/{_esc(squad.get('deal_id'))}">
          <div><b>{_esc(squad.get('deal_id'))} · {_esc(squad.get('category'))}</b><small>{_esc(squad.get('status'))} · {squad.get('supplier_count',0)} proveedores</small></div>
          <div class="sn-chips">{chips}</div>
        </a>'''

    return f'''
    <section class="sn-wrap">
      <div class="sn-top">
        <div><div class="sn-eye">AUTONOMOUS PROCUREMENT · SUPPLIER NETWORK</div><h2>Red viva de proveedores</h2><p>Performance observable + categoría + trazabilidad + diversidad de ruta. Cada deal recibe un supplier squad propio.</p></div>
        <div class="sn-stats"><div><small>PROVEEDORES</small><b>{_esc(report.get('supplier_profiles',0))}</b></div><div><small>TIER A</small><b>{_esc(report.get('tier_a',0))}</b></div><div><small>GAPS</small><b>{_esc(report.get('network_gaps',0))}</b></div></div>
      </div>
      <div class="sn-directive"><small>MOVIMIENTO #1</small><b>{_esc(directive.get('next_action') or directive.get('mode'))}</b><span>{_esc(directive.get('category') or '')}</span></div>
      <div class="sn-grid">{suppliers or '<div class="sn-empty">Sin perfiles todavía.</div>'}</div>
      <h3 class="sn-sub">Supplier squads por deal</h3>
      <div class="sn-squads">{squad_rows or '<div class="sn-empty">Todavía no hay deals con squad.</div>'}</div>
      <div class="sn-foot">El ranking histórico decide a quién consultar primero; nunca reemplaza una cotización vigente. Órdenes, contratos y pagos siguen requiriendo autoridad humana.</div>
    </section>'''


def _squad_detail(state: Dict[str, Any], deal_id: str) -> str:
    squad = (state.get("supplier_squad_index", {}) or {}).get(str(deal_id), {}) or {}
    if not squad:
        return '<section class="snd-wrap"><h3>Supplier Squad</h3><p>Todavía no hay squad materializado para este deal.</p></section>'
    cards = ""
    for row in squad.get("squad", []) or []:
        qm = row.get("quote_metrics", {}) or {}
        cards += f'''
        <div class="snd-card">
          <div><small>{_esc(row.get('role'))}</small><b>{_esc(row.get('supplier'))}</b><span>{_esc(row.get('market') or 'mercado s/d')}</span></div>
          <div><b>{_f(row.get('squad_score')):.0f}</b><small>Squad score</small></div>
          <div><b>{_f(row.get('network_score')):.0f}</b><small>Network score</small></div>
          <div><b>{_f(row.get('category_fit'))*100:.0f}%</b><small>Category fit</small></div>
          <div><b>{qm.get('comparable_quotes',0)}</b><small>Quotes comparables</small></div>
        </div>'''
    return f'''
    <section class="snd-wrap">
      <div class="snd-title"><div><small>PROCUREMENT INTELLIGENCE</small><h3>Supplier Squad · {_esc(deal_id)}</h3></div><span>{_esc(squad.get('status'))}</span></div>
      <p>{_esc(squad.get('rule'))}</p>
      <div class="snd-grid">{cards}</div>
    </section>'''


def css() -> str:
    return '''
    .sn-wrap{margin:12px 0;padding:18px;border:1px solid #594525;border-radius:19px;background:linear-gradient(135deg,#171108,#15120d 55%,#111823);box-shadow:0 16px 42px #0005}.sn-eye{font-size:10px;letter-spacing:.15em;font-weight:900;color:#e5b85b}.sn-wrap h2{margin:5px 0 4px}.sn-wrap p{color:#9e927d}.sn-top{display:flex;justify-content:space-between;gap:16px;align-items:flex-end}.sn-stats{display:flex;gap:7px}.sn-stats>div{min-width:78px;background:#0e0d0a;border:1px solid #40351f;border-radius:10px;padding:8px;text-align:center}.sn-stats small{display:block;color:#8a7959;font-size:8px}.sn-stats b{font-size:20px;color:#e5b85b}.sn-directive{margin-top:12px;padding:10px;border-radius:11px;background:#211909;border:1px solid #5d4821}.sn-directive small,.sn-directive span{display:block;color:#9c8355;font-size:9px}.sn-directive b{display:block;margin:3px 0}.sn-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:12px}.sn-card{border:1px solid #3a3222;border-radius:11px;padding:10px;background:#0d0d0b}.sn-head{display:flex;justify-content:space-between;gap:6px}.sn-head span{color:#e5b85b;font-weight:900}.sn-score{font-size:24px;font-weight:900;margin-top:6px}.sn-score small,.sn-meta,.sn-mini{font-size:9px;color:#817760}.sn-sub{font-size:13px;margin:13px 0 7px}.sn-squads{display:grid;gap:6px}.sn-squad{display:block;text-decoration:none;color:inherit;padding:9px;border:1px solid #2f332f;border-radius:10px;background:#0a0e0d}.sn-squad small{display:block;color:#77817d;margin-top:2px}.sn-chips span{display:inline-block;margin:5px 4px 0 0;padding:3px 6px;border:1px solid #3d4d48;border-radius:99px;color:#9cc8ba;font-size:9px}.sn-foot{margin-top:10px;padding-top:8px;border-top:1px solid #332b1d;font-size:9px;color:#716856}.sn-empty{color:#84775e}.snd-wrap{margin:14px 0;padding:15px;border:1px solid #594525;border-radius:15px;background:#151108}.snd-title{display:flex;justify-content:space-between;align-items:center}.snd-title small{color:#e5b85b;font-size:9px;letter-spacing:.12em}.snd-title h3{margin:3px 0}.snd-title>span{color:#e5b85b;font-weight:900}.snd-wrap p{color:#8f846f;font-size:10px}.snd-grid{display:grid;gap:6px}.snd-card{display:grid;grid-template-columns:2fr repeat(4,1fr);gap:8px;align-items:center;padding:9px;border-radius:9px;background:#0b0c0a;border:1px solid #30291b}.snd-card small,.snd-card span{display:block;color:#786f5d;font-size:9px}.snd-card>div:not(:first-child){text-align:center}@media(max-width:900px){.sn-top{flex-direction:column;align-items:flex-start}.sn-grid{grid-template-columns:1fr}.snd-card{grid-template-columns:1fr 1fr}.snd-card>div:first-child{grid-column:1/-1}.sn-stats{width:100%}.sn-stats>div{flex:1}}
    '''


def inject_supplier_network(base_html: str, state: Dict[str, Any]) -> str:
    out = base_html.replace('</head>', '<style>' + css() + '</style></head>', 1)
    return out.replace('</body>', _network_section(state) + '</body>', 1)


def inject_supplier_squad_detail(base_html: str, state: Dict[str, Any], deal_id: str) -> str:
    out = base_html.replace('</head>', '<style>' + css() + '</style></head>', 1)
    marker = '<section class="drr-box wide"><h3>Decision Ledger del deal</h3>'
    if marker in out:
        return out.replace(marker, _squad_detail(state, deal_id) + marker, 1)
    return out.replace('</body>', _squad_detail(state, deal_id) + '</body>', 1)
