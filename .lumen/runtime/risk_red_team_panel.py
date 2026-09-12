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


def render_risk_red_team(state: Dict[str, Any]) -> str:
    risk = state.get("counterparty_risk", {}) or {}
    profiles = state.get("counterparty_risk_profiles", []) or []
    red = state.get("red_team_audit", {}) or {}
    findings = red.get("findings", []) or []

    if not risk and not red:
        return '<section class="rr-wrap"><div class="rr-eye">RIESGO & AUDITORÍA INTERNA</div><h2>Esperando el primer ciclo</h2><p>La nueva capa todavía no generó perfiles ni hallazgos.</p></section>'

    prof_html = "".join(
        f'<div class="rr-row"><div><b>{_esc(x.get("name"))}</b><small>{_esc(x.get("type"))} · {_esc(x.get("account_id"))}</small></div><span class="rr-tier rr-{_esc(str(x.get("risk_tier") or "watch").lower())}">{_esc(x.get("risk_tier"))}</span><strong>{_f(x.get("risk_score")):.0f}/100</strong></div>'
        for x in profiles[:8]
    ) or '<div class="rr-empty">Sin perfiles de contraparte todavía.</div>'

    findings_html = "".join(
        f'<div class="rr-finding"><div><b>{_esc(x.get("title"))}</b><small>{_esc(x.get("severity"))} · {_esc(x.get("object_type"))} {_esc(x.get("object_id"))}</small></div><span>{"BLOQUEA" if x.get("blocking") else "DESAFÍA"}</span><p>{_esc(x.get("reason"))}</p></div>'
        for x in findings[:8]
    ) or '<div class="rr-empty">Sin contradicciones relevantes detectadas.</div>'

    screen = risk.get("public_screening_this_cycle") or {}
    screen_note = "Sin consulta pública este ciclo"
    if screen:
        screen_note = f"{screen.get('status')} · cobertura {screen.get('coverage')}"

    return f"""
    <section class="rr-wrap">
      <div class="rr-head">
        <div><div class="rr-eye">RIESGO DE CONTRAPARTES · AUDITOR INTERNO</div><h2>Defensa autónoma antes de operar</h2><p>Evalúa identidad/evidencia, conserva incertidumbre y cuestiona decisiones demasiado confiadas antes de salida comercial.</p></div>
        <div class="rr-score"><b>{_f(red.get('audit_score'),100):.0f}</b><small>Puntaje de auditoría</small></div>
      </div>
      <div class="rr-kpis">
        <div><b>{_esc(risk.get('blocked',0))}</b><small>Contrapartes bloqueadas</small></div>
        <div><b>{_esc(risk.get('enhanced_review',0))}</b><small>Revisión reforzada</small></div>
        <div><b>{_esc(red.get('blocking',0))}</b><small>Hallazgos bloqueantes</small></div>
        <div><b>{_esc(red.get('messages_blocked',0))}</b><small>Mensajes frenados</small></div>
      </div>
      <div class="rr-primary"><b>Veredicto del Auditor Interno: {_esc(red.get('verdict') or 'SIN DATOS')}</b><span>{_esc(screen_note)}</span></div>
      <div class="rr-grid">
        <div class="rr-box"><h3>Riesgo de contrapartes</h3>{prof_html}</div>
        <div class="rr-box"><h3>Hallazgos del Red Team</h3>{findings_html}</div>
      </div>
      <div class="rr-foot">Un resultado sin coincidencias públicas no equivale a habilitación legal. Las coincidencias oficiales posibles requieren verificar entidad exacta y norma aplicable antes de progresar.</div>
    </section>
    """


def css() -> str:
    return """
    <style>
    .rr-wrap{margin:14px 0;padding:20px;border:1px solid #714242;border-radius:20px;background:linear-gradient(135deg,#160d0d,#211414 55%,#141012);color:#fff4f1}.rr-eye{font-size:11px;letter-spacing:1.4px;color:#ffaaaa;font-weight:800}.rr-head{display:flex;justify-content:space-between;gap:16px}.rr-head h2{margin:5px 0 3px}.rr-head p,.rr-foot{color:#c9aaaa}.rr-score{text-align:center;min-width:140px;padding:12px;border-radius:15px;background:#2a1818;border:1px solid #6a3b3b}.rr-score b{font-size:30px;display:block}.rr-score small{color:#cfaeae}.rr-kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:14px}.rr-kpis>div{padding:11px;border:1px solid #4a2c2c;border-radius:14px;background:#1b1111}.rr-kpis b{font-size:21px;display:block}.rr-kpis small{color:#b99595}.rr-primary{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-top:12px;padding:12px;border-radius:14px;background:#201313;border:1px solid #503030}.rr-primary span{color:#b99595;font-size:11px}.rr-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}.rr-box{padding:14px;border-radius:16px;background:#171010;border:1px solid #3b2727}.rr-box h3{margin:0 0 8px}.rr-row{display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:1px solid #312121}.rr-row:last-child{border-bottom:0}.rr-row>div{flex:1}.rr-row small{display:block;color:#987d7d}.rr-tier{padding:4px 7px;border-radius:999px;font-size:10px;background:#332323}.rr-blocked{background:#5b2020;color:#ffd0d0}.rr-enhanced_review{background:#5a4520;color:#ffe4a0}.rr-standard{background:#1d4f39;color:#c9ffe5}.rr-watch{background:#263947;color:#cbeaff}.rr-finding{padding:9px 0;border-bottom:1px solid #312121}.rr-finding:last-child{border-bottom:0}.rr-finding>div{display:flex;justify-content:space-between;gap:8px}.rr-finding small{display:block;color:#987d7d}.rr-finding>span{display:inline-block;margin-top:5px;font-size:10px;padding:4px 7px;border-radius:999px;background:#482626}.rr-finding p{font-size:11px;color:#b99d9d;margin:6px 0 0}.rr-foot{margin-top:11px;font-size:11px}.rr-empty{color:#987d7d;padding:8px 0}@media(max-width:800px){.rr-grid,.rr-kpis{grid-template-columns:1fr}.rr-head{flex-direction:column}.rr-score{width:100%;box-sizing:border-box}}
    </style>
    """


def inject_risk_red_team(page: str, state: Dict[str, Any]) -> str:
    block = css() + render_risk_red_team(state)
    marker = "</main>"
    return page.replace(marker, block + marker, 1) if marker in page else page + block
