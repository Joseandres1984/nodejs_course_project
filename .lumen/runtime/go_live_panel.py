from __future__ import annotations

import html
from typing import Any, Dict


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _bool(value: Any) -> str:
    return "LISTO" if bool(value) else "PENDIENTE"


def render_go_live(state: Dict[str, Any]) -> str:
    report = state.get("go_live_orchestrator", {}) or {}
    if not report:
        return '<section class="gl-wrap"><div class="gl-eye">LANZAMIENTO AUTÓNOMO</div><h2>GO-LIVE</h2><p>Esperando la primera evaluación de producción.</p></section>'
    infra = report.get("infra", {}) or {}
    mem = report.get("memory", {}) or {}
    rails = infra.get("payment_rails", {}) or {}
    blockers = infra.get("blockers", []) or []
    warnings = infra.get("warnings", []) or []
    rows = [
        ("PostgreSQL", infra.get("postgres")),
        ("Scout web", infra.get("scout")),
        ("SMTP", infra.get("smtp")),
        ("IMAP", infra.get("imap")),
        ("Divulgación automatización", infra.get("automation_disclosure")),
        ("Adquisición", infra.get("acquisition_ready")),
        ("Monetización", infra.get("monetization_ready")),
    ]
    checks = "".join(
        f'<div class="gl-check"><span>{_esc(name)}</span><b class="{"ok" if ok else "pending"}">{_bool(ok)}</b></div>'
        for name, ok in rows
    )
    blocker_html = "".join(f'<span class="gl-chip bad">{_esc(x.replace("_", " "))}</span>' for x in blockers) or '<span class="gl-chip ok">sin bloqueos críticos</span>'
    warning_html = "".join(f'<span class="gl-chip warn">{_esc(x.replace("_", " "))}</span>' for x in warnings) or '<span class="gl-chip ok">sin advertencias</span>'
    return f"""
    <section class="gl-wrap">
      <div class="gl-head">
        <div><div class="gl-eye">LANZAMIENTO AUTÓNOMO · PRODUCCIÓN</div><h2>GO-LIVE</h2><p>Salida real progresiva con canario, promoción automática y rollback.</p></div>
        <div class="gl-stage"><small>ETAPA</small><b>{_esc(report.get('stage') or 'PRELANZAMIENTO')}</b><span>{_esc(report.get('launch_status') or '')}</span></div>
      </div>
      <div class="gl-kpis">
        <div><small>Cap por ciclo</small><b>{_esc(report.get('effective_outbound_cap',0))}</b></div>
        <div><small>Ciclos estables</small><b>{_esc(mem.get('stable_cycles',0))}</b></div>
        <div><small>Enviados</small><b>{_esc(mem.get('sent_total',0))}</b></div>
        <div><small>Fallidos</small><b>{_esc(mem.get('failed_total',0))}</b></div>
        <div><small>Rails verificados</small><b>{_esc(int(rails.get('verified_domestic',0) or 0)+int(rails.get('verified_international',0) or 0))}</b></div>
      </div>
      <div class="gl-grid">
        <div class="gl-box"><h3>Checklist de lanzamiento</h3>{checks}</div>
        <div class="gl-box"><h3>Estado de control</h3><p><b>Outbound real:</b> {'HABILITADO' if report.get('outbound_allowed') else 'CERRADO'}</p><p><b>Salud operativa:</b> {_esc(infra.get('operations_health_score'))}/100</p><p><b>Modo:</b> {_esc(report.get('requested_mode'))} · autopromoción {'sí' if report.get('auto_promote') else 'no'}</p><div class="gl-chips">{blocker_html}{warning_html}</div></div>
      </div>
      <div class="gl-foot">CANARIO: 1 envío/ciclo → LIMITADO: 2 → GOBERNADO: máximo constitucional. Fallas relevantes provocan rollback automático. Contratos, pagos, órdenes y aceptación vinculante siguen requiriendo autoridad humana.</div>
    </section>
    """


def css() -> str:
    return """
    <style>
    .gl-wrap{margin:14px 0;padding:20px;border:1px solid #23505c;border-radius:20px;background:linear-gradient(135deg,#08171d,#0c222a 60%,#09161a);color:#e9fbff}.gl-eye{font-size:11px;letter-spacing:1.5px;color:#78d5e8;font-weight:800}.gl-head{display:flex;justify-content:space-between;gap:16px}.gl-head h2{margin:5px 0 4px}.gl-head p{margin:0;color:#a8c4ca}.gl-stage{min-width:240px;padding:12px 14px;border-radius:15px;background:#0f2a33;border:1px solid #285766}.gl-stage small,.gl-stage b,.gl-stage span{display:block}.gl-stage small{color:#79cddd;font-size:9px}.gl-stage b{font-size:20px;margin:4px 0}.gl-stage span{color:#a9c9cf}.gl-kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin:14px 0}.gl-kpis>div{padding:11px;border-radius:13px;background:#0d252d;border:1px solid #244954}.gl-kpis small{display:block;color:#7da8b2}.gl-kpis b{display:block;margin-top:4px;font-size:18px}.gl-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.gl-box{padding:14px;border-radius:15px;background:#0b2027;border:1px solid #244550}.gl-box h3{margin:0 0 10px}.gl-check{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #17363f}.gl-check:last-child{border-bottom:0}.gl-check b{font-size:10px;padding:4px 7px;border-radius:999px}.gl-check .ok,.gl-chip.ok{background:#123c2b;color:#a8efc6}.gl-check .pending,.gl-chip.bad{background:#472626;color:#ffbaba}.gl-chip.warn{background:#493b19;color:#ffe4a0}.gl-chips{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}.gl-chip{font-size:10px;padding:5px 8px;border-radius:999px}.gl-foot{margin-top:12px;color:#86aeb7;font-size:11px}@media(max-width:800px){.gl-head{flex-direction:column}.gl-stage{min-width:0}.gl-kpis{grid-template-columns:1fr 1fr}.gl-grid{grid-template-columns:1fr}}
    </style>
    """


def inject_go_live(page: str, state: Dict[str, Any]) -> str:
    block = css() + render_go_live(state)
    marker = "</main>"
    return page.replace(marker, block + marker, 1) if marker in page else page + block
