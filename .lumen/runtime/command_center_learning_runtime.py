from __future__ import annotations

"""Additive Command Center learning/intelligence panel.

Loaded after command_center_truth_runtime. It only reads persisted state and adds owner-facing
observability. It grants no new business authority.
"""

import html
from typing import Any, Dict

import control_tower as _ct

VERSION = "1.0-command-center-learning"
_ORIGINAL_BUILD = _ct.build_control_tower
_ORIGINAL_RENDER = _ct.render_control_tower


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def learning_build_control_tower(state: Dict[str, Any], db_status: Dict[str, Any]) -> Dict[str, Any]:
    snapshot = dict(_ORIGINAL_BUILD(state, db_status) or {})
    learning = state.get("continuous_learning", {}) or {}
    crd = state.get("continuous_revenue_drive", {}) or {}
    lab = state.get("self_improvement_lab", {}) or {}
    external = learning.get("external_intelligence", {}) or {}
    ledger = learning.get("improvement_ledger", {}) or {}
    profit = state.get("profit_learning", {}) or {}

    snapshot["learning"] = {
        "status": learning.get("status") or "waiting_first_cycle",
        "updated_at": learning.get("updated_at"),
        "crd_mode": crd.get("mode"),
        "crd_lane": crd.get("primary_lane"),
        "crd_action": crd.get("primary_action"),
        "self_improvement_code": (lab.get("primary_proposal") or {}).get("code") or (learning.get("self_improvement", {}) or {}).get("primary_code"),
        "self_improvement_title": (lab.get("primary_proposal") or {}).get("title") or (learning.get("self_improvement", {}) or {}).get("primary_title"),
        "autonomous_tests": _i(lab.get("autonomous_tests") or (learning.get("self_improvement", {}) or {}).get("autonomous_tests")),
        "code_change_proposals": _i(lab.get("code_change_proposals") or (learning.get("self_improvement", {}) or {}).get("code_change_proposals")),
        "external_signals": _i(external.get("signals_total")),
        "external_sources": _i(external.get("sources_total")),
        "external_high_confidence": _i(external.get("high_confidence_signals")),
        "external_top": list(external.get("top_signals", []) or [])[:5],
        "ledger_entries": _i(ledger.get("entries")),
        "ledger_observing": _i(ledger.get("observing")),
        "ledger_supported": _i(ledger.get("supported")),
        "ledger_demoted": _i(ledger.get("demoted")),
        "ledger_human": _i(ledger.get("human_review_required")),
        "ledger_latest": list(ledger.get("latest", []) or [])[-5:],
        "profit_primary_category": profit.get("primary_category"),
        "exploit_pct": profit.get("exploit_pct"),
        "explore_pct": profit.get("explore_pct"),
        "governance": learning.get("governance") or {},
    }
    state["control_tower"] = snapshot
    return snapshot


def _signal_rows(rows: list[Dict[str, Any]]) -> str:
    if not rows:
        return '<div class="learning-empty">Todavía no hay señales externas calificadas en este ciclo.</div>'
    out = []
    for row in rows[:5]:
        conf = int(round(_f(row.get("confidence")) * 100))
        relevance = int(round(_f(row.get("commercial_relevance")) * 100))
        out.append(
            '<div class="learning-row">'
            f'<div><div class="learning-title">{_esc(row.get("title") or "Señal externa")}</div>'
            f'<div class="learning-small">{_esc(row.get("source_domain") or "fuente pública")} · {_esc(row.get("source_class") or "sin clasificar")}</div></div>'
            f'<div class="learning-score">C {conf}% · R {relevance}%</div>'
            '</div>'
        )
    return "".join(out)


def _ledger_rows(rows: list[Dict[str, Any]]) -> str:
    if not rows:
        return '<div class="learning-empty">El historial verificable se poblará con los próximos ciclos.</div>'
    out = []
    for row in reversed(rows[-5:]):
        status = str(row.get("status") or "OBSERVING")
        css = "learn-good" if status == "SUPPORTED" else "learn-bad" if status == "DEMOTED" else "learn-warn" if status == "HUMAN_REVIEW_REQUIRED" else ""
        out.append(
            '<div class="learning-row">'
            f'<div><div class="learning-title">{_esc(row.get("hypothesis") or row.get("code") or "Mejora")}</div>'
            f'<div class="learning-small">{_esc(row.get("target_metric") or "métrica en observación")} · muestras {_i(row.get("samples"))}</div></div>'
            f'<div class="learning-status {css}">{_esc(status)}</div>'
            '</div>'
        )
    return "".join(out)


def learning_render_control_tower(snapshot: Dict[str, Any]) -> str:
    page = _ORIGINAL_RENDER(snapshot)
    learning = snapshot.get("learning", {}) or {}

    css = """
<style id="lumen-learning-css">
.learning-section{margin-top:14px}.learning-heading{display:flex;justify-content:space-between;gap:12px;align-items:end;margin:0 0 10px}.learning-heading h2{margin:0}.learning-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.learning-wide{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px}.learning-kpi{font-size:24px;font-weight:850;margin-top:7px}.learning-row{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;padding:9px 0;border-bottom:1px solid #17303e}.learning-row:last-child{border-bottom:0}.learning-title{font-weight:750;line-height:1.25}.learning-small{font-size:11px;color:var(--muted);margin-top:3px}.learning-score,.learning-status{white-space:nowrap;font-size:11px;color:var(--blue);font-weight:750}.learn-good{color:var(--good)}.learn-bad{color:var(--bad)}.learn-warn{color:var(--warn)}.learning-empty{font-size:12px;color:var(--muted);padding:12px 0}.learning-policy{margin-top:8px;font-size:11px;color:var(--muted);line-height:1.45}
@media(max-width:1050px){.learning-grid{grid-template-columns:1fr 1fr}.learning-wide{grid-template-columns:1fr}}
@media(max-width:620px){body{padding:10px!important}.hero,.learning-grid,.learning-wide{grid-template-columns:1fr!important}.card{border-radius:13px;padding:13px}.top{gap:8px}.learning-heading{align-items:flex-start;flex-direction:column}.learning-row{flex-direction:column;gap:5px}.learning-score,.learning-status{white-space:normal}.metric,.learning-kpi{font-size:21px}.activity{max-height:none}}
</style>
"""
    if "lumen-learning-css" not in page:
        page = page.replace("</head>", css + "</head>", 1)

    crd_mode = learning.get("crd_mode") or "esperando ciclo"
    lane = learning.get("crd_lane") or "—"
    action = learning.get("crd_action") or "El próximo ciclo definirá la acción prioritaria."
    improvement = learning.get("self_improvement_title") or learning.get("self_improvement_code") or "Acumulando evidencia"
    external_total = _i(learning.get("external_signals"))
    high_conf = _i(learning.get("external_high_confidence"))
    supported = _i(learning.get("ledger_supported"))
    demoted = _i(learning.get("ledger_demoted"))
    ledger_total = _i(learning.get("ledger_entries"))
    primary_category = learning.get("profit_primary_category") or "Sin concentración todavía"
    exploit = learning.get("exploit_pct")
    explore = learning.get("explore_pct")

    section = f"""
<section class="learning-section">
  <div class="learning-heading"><h2>Aprendizaje, mejora continua e inteligencia externa</h2><div class="small">{_esc(learning.get('updated_at') or 'esperando primer ciclo')}</div></div>
  <div class="learning-grid">
    <div class="card"><div class="label">Continuous Revenue Drive</div><div class="learning-kpi lime">{_esc(crd_mode)}</div><div class="small">Carril: {_esc(lane)}</div><div class="learning-policy">{_esc(action)}</div></div>
    <div class="card"><div class="label">Mejora prioritaria</div><div class="learning-kpi blue">{_esc(learning.get('self_improvement_code') or 'LEARNING')}</div><div class="small">{_esc(improvement)}</div><div class="learning-policy">Tests reversibles autónomos: {_i(learning.get('autonomous_tests'))} · cambios de código: {_i(learning.get('code_change_proposals'))} requieren revisión.</div></div>
    <div class="card"><div class="label">Inteligencia externa</div><div class="learning-kpi good">{external_total}</div><div class="small">{_i(learning.get('external_sources'))} fuentes · {high_conf} señales de alta confianza</div><div class="learning-policy">La web se trata como evidencia no confiable hasta corroborarla; nunca como instrucciones ejecutables.</div></div>
    <div class="card"><div class="label">Historial de mejora</div><div class="learning-kpi">{ledger_total}</div><div class="small"><span class="learn-good">{supported} respaldadas</span> · <span class="learn-bad">{demoted} degradadas</span> · {_i(learning.get('ledger_observing'))} observando</div><div class="learning-policy">Hipótesis → evidencia → métrica → resultado → conservar, degradar o seguir midiendo.</div></div>
  </div>
  <div class="learning-wide">
    <div class="card"><h2>Señales externas mejor calificadas</h2>{_signal_rows(list(learning.get('external_top', []) or []))}</div>
    <div class="card"><h2>Improvement Ledger</h2>{_ledger_rows(list(learning.get('ledger_latest', []) or []))}</div>
  </div>
  <div class="card" style="margin-top:10px"><div class="label">Aprendizaje de rentabilidad</div><div class="learning-title" style="margin-top:6px">Foco actual: {_esc(primary_category)}</div><div class="learning-small">Explotación: {_esc(exploit if exploit is not None else '—')}% · Exploración: {_esc(explore if explore is not None else '—')}% · El foco cambia sólo con evidencia acumulada.</div></div>
</section>
"""
    if "Aprendizaje, mejora continua e inteligencia externa" not in page:
        page = page.replace("</body>", section + "</body>", 1)
    return page


_ct.build_control_tower = learning_build_control_tower
_ct.render_control_tower = learning_render_control_tower
print({"command_center_learning_runtime": {"version": VERSION, "status": "active", "mobile": "single_column_under_620px"}}, flush=True)
