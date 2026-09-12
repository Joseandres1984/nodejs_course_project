from __future__ import annotations

import html
from typing import Any, Dict


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else "—"))


def inject_venture_builder(page: str, state: Dict[str, Any]) -> str:
    report = state.get("venture_builder", {}) or {}
    directive = report.get("directive", {}) or {}
    primary = report.get("primary_venture", {}) or {}
    ventures = report.get("ventures", []) or []
    stages = report.get("stage_counts", {}) or {}

    cards = []
    for item in ventures[:8]:
        evidence = item.get("evidence", {}) or {}
        blockers = ", ".join(str(x) for x in (item.get("blockers") or [])[:4]) or "sin bloqueos críticos"
        cards.append(
            f"<div class='ct-card'>"
            f"<div class='ct-kicker'>{_esc(item.get('stage'))} · {_esc(item.get('type'))}</div>"
            f"<h3>{_esc(item.get('category'))}</h3>"
            f"<div class='ct-big'>{_esc(item.get('score'))}/100</div>"
            f"<p>Confianza {_esc(item.get('confidence'))} · Mercado {_esc(item.get('market'))}</p>"
            f"<p>Demanda {_esc(evidence.get('buyers_with_demand'))} · Proveedores {_esc(evidence.get('verified_suppliers'))} · Ofertas reales {_esc(evidence.get('real_offers'))}</p>"
            f"<p>Transacciones atribuibles {_esc(item.get('real_transactions'))} · Beneficio realizado USD {_esc(item.get('realized_profit_usd'))}</p>"
            f"<p><strong>Bloqueos:</strong> {_esc(blockers)}</p>"
            f"</div>"
        )

    stage_summary = " · ".join(f"{k}: {v}" for k, v in stages.items() if v)
    panel = f"""
<section class='ct-section'>
  <div class='ct-section-head'>
    <div>
      <div class='ct-kicker'>AUTONOMOUS VENTURE BUILDER</div>
      <h2>New Business Creation Studio</h2>
    </div>
    <div class='ct-pill'>{_esc(report.get('venture_count', 0))} ventures</div>
  </div>
  <div class='ct-grid'>
    <div class='ct-card ct-accent'>
      <div class='ct-kicker'>VENTURE #1</div>
      <h3>{_esc(primary.get('category'))}</h3>
      <div class='ct-big'>{_esc(primary.get('score'))}/100</div>
      <p>{_esc(primary.get('thesis'))}</p>
      <p><strong>Etapa:</strong> {_esc(primary.get('stage'))} · <strong>Confianza:</strong> {_esc(primary.get('confidence'))}</p>
      <p><strong>Próxima acción:</strong> {_esc(directive.get('next_action_title'))}</p>
      <p><strong>Research autónomo:</strong> {'habilitado' if directive.get('research_validation_allowed') else 'en pausa'}</p>
    </div>
    <div class='ct-card'>
      <div class='ct-kicker'>DISCIPLINA DE VALIDACIÓN</div>
      <h3>Idea ≠ negocio</h3>
      <p>Una venture solo avanza con demanda, oferta, canales y evidencia trazable. El pipeline no alcanza para llamarla escalable.</p>
      <p>Escala únicamente después de transacciones reales atribuibles y beneficio realizado positivo.</p>
      <p><strong>Etapas activas:</strong> {_esc(stage_summary or 'sin ventures activas')}</p>
    </div>
  </div>
  <div class='ct-grid'>{''.join(cards) if cards else '<div class="ct-card"><p>Todavía no hay hipótesis con evidencia suficiente para mostrar.</p></div>'}</div>
</section>
"""
    marker = "</main>"
    if marker in page:
        return page.replace(marker, panel + marker, 1)
    return page + panel
