from __future__ import annotations

import html
from typing import Any, Dict
import control_tower as _ct

VERSION = "1.0-command-center-canonical-truth"
_ORIGINAL_BUILD = _ct.build_control_tower
_ORIGINAL_RENDER = _ct.render_control_tower

def _esc(v: Any) -> str:
    return html.escape(str(v if v is not None else ""), quote=True)
def _i(v: Any) -> int:
    try: return int(v or 0)
    except (TypeError, ValueError): return 0

def canonical_build(state: Dict[str, Any], db_status: Dict[str, Any]) -> Dict[str, Any]:
    snap = dict(_ORIGINAL_BUILD(state, db_status) or {})
    snap["canonical_revenue_truth"] = dict(state.get("canonical_revenue_truth", {}) or {})
    state["control_tower"] = snap
    return snap

def canonical_render(snapshot: Dict[str, Any]) -> str:
    page = _ORIGINAL_RENDER(snapshot)
    truth = snapshot.get("canonical_revenue_truth", {}) or {}
    c = truth.get("counts", {}) or {}
    lane = truth.get("recommended_lane") or "esperando ciclo"
    reason = truth.get("reason") or "El próximo ciclo calculará la verdad comercial canónica."
    qdeals = list(truth.get("quarantined_deals", []) or [])[:4]
    qhtml = "".join(
        f'<div class="crt-row"><span>{_esc(x.get("id") or "deal")}</span><small>{_esc(", ".join(x.get("reasons") or []) or "sin motivo")}</small></div>'
        for x in qdeals
    ) or '<div class="crt-muted">No hay deals en cuarentena.</div>'
    css = """
<style id="lumen-crt-css">
.crt{margin-top:14px}.crt-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.crt-num{font-size:24px;font-weight:850;margin-top:6px}.crt-row{display:flex;justify-content:space-between;gap:12px;padding:7px 0;border-bottom:1px solid #17303e}.crt-row small,.crt-muted{font-size:11px;color:var(--muted)}.crt-rule{font-size:11px;color:var(--muted);line-height:1.45;margin-top:8px}@media(max-width:800px){.crt-grid{grid-template-columns:1fr 1fr}}@media(max-width:620px){.crt-grid{grid-template-columns:1fr!important}.crt-row{flex-direction:column;gap:3px}}
</style>
"""
    if "lumen-crt-css" not in page:
        page = page.replace("</head>", css + "</head>", 1)
    section = f"""
<section class="crt">
  <div class="learning-heading"><h2>Canonical Revenue Truth</h2><div class="small">una sola verdad para CRD · Allocator · Autonomy · First Cash</div></div>
  <div class="crt-grid">
    <div class="card"><div class="label">Carril canónico</div><div class="crt-num lime">{_esc(lane)}</div><div class="crt-rule">{_esc(reason)}</div></div>
    <div class="card"><div class="label">Oportunidades</div><div class="crt-num">{_i(c.get('canonical_opportunities'))}</div><div class="crt-rule">canónicas · raw {_i(c.get('raw_market_opportunities'))} · cuarentena {_i(c.get('quarantined_opportunities'))}</div></div>
    <div class="card"><div class="label">Deals</div><div class="crt-num">{_i(c.get('canonical_deals'))}</div><div class="crt-rule">canónicos · raw {_i(c.get('raw_deals'))} · cuarentena {_i(c.get('quarantined_deals'))}</div></div>
    <div class="card"><div class="label">Ruta a cierre</div><div class="crt-num">{_i(c.get('closing_eligible_deals'))}</div><div class="crt-rule">elegibles para cierre · {_i(c.get('canonical_close_ready'))} close-ready</div></div>
  </div>
  <div class="card" style="margin-top:10px"><h2>Deals excluidos de prioridad comercial</h2>{qhtml}<div class="crt-rule">Las filas históricas se conservan para auditoría, pero no pueden impulsar cierre sin oportunidad evidence-backed y linaje trazable.</div></div>
</section>
"""
    if "Canonical Revenue Truth" not in page:
        page = page.replace("</body>", section + "</body>", 1)
    return page

_ct.build_control_tower = canonical_build
_ct.render_control_tower = canonical_render
print({"command_center_canonical_truth_runtime": {"version": VERSION, "status": "active"}}, flush=True)
