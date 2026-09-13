from __future__ import annotations

import html
from typing import Any, Dict

import workforce_panel as base


def _e(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _scale(state: Dict[str, Any]) -> Dict[str, Any]:
    workforce = state.get("agent_workforce", {}) or {}
    last = workforce.get("last_cycle", {}) or {}
    decision = workforce.get("scale_decision", {}) or {}
    policy = workforce.get("elastic_policy", {}) or {}
    return {
        "active": int(workforce.get("roster_count") or last.get("fleet_size") or 0),
        "previous": int(decision.get("previous_fleet_size") or last.get("previous_fleet_size") or 0),
        "raw_target": int(decision.get("raw_target") or last.get("raw_target_fleet_size") or 0),
        "direction": str(decision.get("direction") or last.get("scale_direction") or "waiting"),
        "score": decision.get("workload_score", last.get("workload_score", 0)),
        "reason": str(decision.get("reason") or last.get("scale_reason") or "—"),
        "min": int(policy.get("min_fleet") or last.get("fleet_min") or 10),
        "max": int(policy.get("max_fleet") or last.get("fleet_max") or 100),
        "bands": policy.get("bands") or last.get("scale_bands") or [10, 25, 50, 75, 100],
    }


def inject_workforce_strip(base_html: str, state: Dict[str, Any]) -> str:
    out = base.inject_workforce_strip(base_html, state)
    scale = _scale(state)
    out = out.replace("PLANTILLA DIGITAL AUTÓNOMA", "PLANTILLA DIGITAL ELÁSTICA")
    old = "Meta-LUMEN reparte trabajo en paralelo. Las búsquedas externas siguen compartiendo presupuesto, evidencia y límites constitucionales."
    new = (
        f"Meta-LUMEN ajusta automáticamente la plantilla entre {scale['min']} y {scale['max']} agentes según la carga real. "
        f"Carga actual: {scale['score']}/100 · decisión: {scale['direction']}. El presupuesto externo sigue centralizado."
    )
    out = out.replace(old, new)
    return out


def render_workforce_page(state: Dict[str, Any]) -> str:
    out = base.render_workforce_page(state)
    scale = _scale(state)
    active = scale["active"] or 0
    out = out.replace(
        "50 especialistas coordinados por Meta-LUMEN. Paralelismo alto, gasto y autoridad centralizados.",
        f"{active} especialistas activos coordinados por Meta-LUMEN. La dotación escala sola entre {scale['min']} y {scale['max']} según el trabajo disponible; gasto y autoridad siguen centralizados.",
    )
    out = out.replace(
        '<div><a href="/command-center">← Command Center</a></div>',
        '<div><a href="/casework">Deep Work · expedientes</a> · <a href="/command-center">← Command Center</a></div>',
    )
    panel = f'''
    <section class="panel">
      <h2>Escalado automático</h2>
      <div class="roles">
        <div class="card"><small>Activos</small><b>{_e(scale['active'])}</b><span>agentes este ciclo</span></div>
        <div class="card"><small>Anterior</small><b>{_e(scale['previous'])}</b><span>dotación previa</span></div>
        <div class="card"><small>Objetivo bruto</small><b>{_e(scale['raw_target'])}</b><span>antes de anti-thrashing</span></div>
        <div class="card"><small>Carga</small><b>{_e(scale['score'])}</b><span>sobre 100</span></div>
        <div class="card"><small>Decisión</small><b style="font-size:16px">{_e(scale['direction'])}</b><span>{_e(scale['reason'])}</span></div>
      </div>
      <p class="muted">Bandas disponibles: {_e(' → '.join(str(x) for x in scale['bands']))}. Meta-LUMEN sube o baja una banda por ciclo salvo urgencia comercial u operativa.</p>
    </section>
    '''
    marker = '<section class="roles">'
    if marker in out:
        out = out.replace(marker, panel + marker, 1)
    return out
