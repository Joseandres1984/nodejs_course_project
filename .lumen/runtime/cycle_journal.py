from __future__ import annotations

import html
import os
from datetime import datetime, timezone
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

import psycopg
from psycopg.types.json import Jsonb


DATABASE_URL = os.getenv("DATABASE_URL", "")
TZ_NAME = os.getenv("LUMEN_SCOUT_TIMEZONE", "America/Argentina/Buenos_Aires") or "America/Argentina/Buenos_Aires"
try:
    LOCAL_TZ = ZoneInfo(TZ_NAME)
except Exception:
    LOCAL_TZ = timezone.utc


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _e(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _money(value: Any) -> str:
    try:
        return f"USD {float(value):,.2f}"
    except (TypeError, ValueError):
        return "USD 0.00"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_state_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S UTC", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _local_label(value: datetime | None = None) -> str:
    dt = value or _now_utc()
    return dt.astimezone(LOCAL_TZ).strftime("%d/%m/%Y %H:%M:%S")


def ensure_cycle_journal_db() -> bool:
    if not DATABASE_URL:
        return False
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS lumen_cycle_journal (
                        cycle INTEGER PRIMARY KEY,
                        recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        local_time TEXT NOT NULL,
                        status TEXT NOT NULL,
                        source TEXT NOT NULL,
                        payload JSONB NOT NULL
                    )
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS lumen_cycle_journal_recorded_idx ON lumen_cycle_journal(recorded_at DESC)")
        return True
    except Exception:
        return False


def _previous_payload(cycle: int) -> Dict[str, Any]:
    if not ensure_cycle_journal_db():
        return {}
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT payload FROM lumen_cycle_journal WHERE cycle < %s ORDER BY cycle DESC LIMIT 1", (cycle,))
                row = cur.fetchone()
        return row[0] if row and isinstance(row[0], dict) else {}
    except Exception:
        return {}


def _commission_collected(state: Dict[str, Any]) -> float:
    total = 0.0
    for row in state.get("revenue_ledger", []) or []:
        if str(row.get("kind") or "") != "commission_settlement":
            continue
        if str(row.get("status") or "") not in {"realized", "realized_partial"}:
            continue
        total += max(0.0, _f(row.get("amount")))
    return round(total, 2)


def _real_transactions(state: Dict[str, Any]) -> int:
    statuses = {"closed", "settled", "paid", "completed", "delivered", "invoiced"}
    return sum(
        1 for row in state.get("transactions", []) or []
        if str(row.get("status") or "").lower() in statuses
        and str(row.get("status") or "").lower() not in {"closed_simulated", "simulated"}
    )


def build_cycle_entry(state: Dict[str, Any], *, source: str = "worker", previous: Dict[str, Any] | None = None) -> Dict[str, Any]:
    cycle = _i(state.get("ticks"))
    telemetry = state.get("connector_telemetry", {}) or {}
    meta = state.get("meta_autonomy", {}) or {}
    coo = telemetry.get("autonomous_coo", {}) or state.get("operations_control", {}) or {}
    scout = telemetry.get("scout", {}) or {}
    retail = scout.get("retail_velocity", {}) or state.get("retail_velocity_radar", {}) or {}
    retail_product = retail.get("primary_product", {}) or {}
    kpis = state.get("business_kpis", {}) or {}
    funnel = kpis.get("funnel", {}) or {}
    finance = kpis.get("finance", {}) or (state.get("cfo", {}) or {}).get("financial_snapshot", {}) or {}
    management = state.get("autonomous_management", {}) or {}
    management_primary = management.get("primary_management_priority", {}) or {}
    master = state.get("master_governance", {}) or {}
    controller = state.get("business_controller", {}) or {}
    improvement = state.get("self_improvement_lab", {}) or {}
    improvement_primary = improvement.get("primary_proposal", {}) or {}
    revenue = state.get("revenue_factory", {}) or {}
    revenue_directive = revenue.get("directive", {}) or {}

    engine_failures = len((coo.get("engine_health", {}) or {}).get("failed_now", []) or [])
    circuits = len((coo.get("engine_health", {}) or {}).get("circuits_open", []) or [])
    meta_errors = list(meta.get("engine_errors", []) or [])
    coo_status = str(coo.get("status") or "unknown")
    meta_status = str(meta.get("status") or "unknown")
    healthy = coo_status == "healthy" and meta_status in {"healthy", "unknown"} and engine_failures == 0 and circuits == 0 and not meta_errors
    status = "HEALTHY" if healthy else "DEGRADED"

    counts = {
        "research_leads": _i(funnel.get("research_leads"), len(state.get("research_leads", []) or [])),
        "candidate_accounts": _i(funnel.get("candidate_accounts"), len(state.get("candidate_accounts", []) or [])),
        "verified_companies": _i(funnel.get("verified_companies")),
        "verified_buyers": _i(funnel.get("verified_buyers")),
        "verified_suppliers": _i(funnel.get("verified_suppliers")),
        "buyers_with_demand": _i(funnel.get("buyers_with_public_demand")),
        "opportunities": _i(funnel.get("evidence_backed_opportunities"), len(state.get("market_opportunities", []) or [])),
        "requirements_ready": _i(funnel.get("requirements_ready_for_rfq")),
        "real_offers": _i(funnel.get("real_offers")),
        "proposals": _i(funnel.get("proposals")),
        "close_ready": _i(funnel.get("close_ready")),
        "real_transactions": _real_transactions(state),
        "market_inquiries": len(state.get("market_inquiries", []) or []),
        "published_listings": sum(1 for x in state.get("autonomous_listings", []) or [] if x.get("status") == "published"),
    }

    prev_counts = (previous or {}).get("counts", {}) or {}
    deltas = {key: value - _i(prev_counts.get(key), value) for key, value in counts.items()}

    last_tick_dt = _parse_state_time(state.get("last_tick")) or _now_utc()
    entry = {
        "cycle": cycle,
        "recorded_at_utc": _now_utc().isoformat(),
        "cycle_time_utc": last_tick_dt.isoformat(),
        "local_time": _local_label(last_tick_dt),
        "timezone": TZ_NAME,
        "source": source,
        "status": status,
        "system": {
            "meta_status": meta_status,
            "coo_status": coo_status,
            "coo_health_score": _f(coo.get("health_score")),
            "engine_failures": engine_failures,
            "circuits_open": circuits,
            "outbound_allowed": bool(telemetry.get("live_outbound_allowed")),
            "postgres_connected": bool((telemetry.get("postgres", {}) or {}).get("connected")),
            "meta_errors": meta_errors[:5],
        },
        "decision": {
            "company_mode": str(meta.get("company_mode") or master.get("company_mode") or "—"),
            "revenue_directive": str(meta.get("revenue_directive") or revenue_directive.get("code") or "—"),
            "recommended_scenario": str(meta.get("recommended_scenario") or "—"),
            "management_priority": str(meta.get("management_priority") or management_primary.get("code") or "—"),
            "management_department": str(meta.get("management_department") or management_primary.get("department") or "—"),
            "management_title": str(management_primary.get("title") or ""),
            "controller_mode": str(meta.get("controller_mode") or controller.get("control_mode") or "—"),
            "self_improvement_primary": str(meta.get("self_improvement_primary") or improvement_primary.get("code") or "—"),
            "next_action": str(management_primary.get("title") or revenue_directive.get("title") or "Continuar ejecución autónoma"),
        },
        "research": {
            "scout_queries": _i(scout.get("queries")),
            "new_leads_tick": _i(scout.get("new_leads")),
            "demand_queries": _i(scout.get("demand_queries")) + _i((scout.get("demand_hunter", {}) or {}).get("queries")),
            "demand_signals_verified_tick": _i(scout.get("demand_signals_verified")) + _i((scout.get("demand_hunter", {}) or {}).get("signals_found")),
            "budget_remaining": _i(scout.get("budget_remaining_total"), _i(scout.get("budget_remaining"))),
            "budget_used_today": _i(scout.get("budget_used_today")),
            "retail_queries": _i(retail.get("queries")),
            "retail_lane": str(retail.get("lane") or retail_product.get("lane") or ""),
            "retail_product": str(retail_product.get("product") or ""),
            "retail_velocity_score": _f(retail_product.get("velocity_score")),
            "retail_reported_sales": _i(retail_product.get("reported_sales")),
            "retail_signals_total": _i(retail.get("signals_total")),
        },
        "counts": counts,
        "delta": deltas,
        "money": {
            "risk_adjusted_expected_profit_usd": round(_f(finance.get("risk_adjusted_expected_profit_usd")), 2),
            "realized_profit_usd": round(_f(finance.get("realized_profit_usd")), 2),
            "commission_collected_usd": _commission_collected(state),
        },
        "blockers": list(kpis.get("bottlenecks", []) or [])[:8],
    }

    retail_text = ""
    if entry["research"]["retail_product"]:
        retail_text = f" · retail {entry['research']['retail_product']} {entry['research']['retail_velocity_score']:.0f}/100"
    entry["summary"] = (
        f"{status} · {entry['decision']['company_mode']} · foco {entry['decision']['management_department']} · "
        f"{entry['research']['scout_queries']} búsquedas · {entry['research']['new_leads_tick']:+d} lead(s) del Scout"
        f"{retail_text} · oportunidades {counts['opportunities']} · comisión cobrada {_money(entry['money']['commission_collected_usd'])}"
    )
    return entry


def record_cycle(state: Dict[str, Any], *, source: str = "worker") -> Dict[str, Any]:
    cycle = _i(state.get("ticks"))
    if cycle <= 0:
        return {"stored": False, "reason": "cycle_not_started"}
    if not ensure_cycle_journal_db():
        return {"stored": False, "reason": "journal_db_unavailable", "cycle": cycle}
    previous = _previous_payload(cycle)
    entry = build_cycle_entry(state, source=source, previous=previous)
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO lumen_cycle_journal(cycle, recorded_at, local_time, status, source, payload)
                    VALUES (%s, NOW(), %s, %s, %s, %s)
                    ON CONFLICT (cycle) DO UPDATE SET
                        recorded_at=EXCLUDED.recorded_at,
                        local_time=EXCLUDED.local_time,
                        status=EXCLUDED.status,
                        source=EXCLUDED.source,
                        payload=EXCLUDED.payload
                    """,
                    (cycle, entry["local_time"], entry["status"], source, Jsonb(entry)),
                )
        return {"stored": True, "cycle": cycle, "entry": entry}
    except Exception as exc:
        return {"stored": False, "reason": f"{type(exc).__name__}: {str(exc)[:180]}", "cycle": cycle}


def cycle_exists(cycle: int) -> bool:
    if cycle <= 0 or not ensure_cycle_journal_db():
        return False
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM lumen_cycle_journal WHERE cycle=%s", (cycle,))
                return bool(cur.fetchone())
    except Exception:
        return False


def bootstrap_current_cycle(state: Dict[str, Any]) -> Dict[str, Any]:
    cycle = _i(state.get("ticks"))
    if cycle <= 0:
        return {"stored": False, "reason": "cycle_not_started"}
    if cycle_exists(cycle):
        return {"stored": False, "reason": "already_recorded", "cycle": cycle}
    return record_cycle(state, source="bootstrap_current_state")


def fetch_cycles(*, page: int = 1, per_page: int = 50) -> Dict[str, Any]:
    page = max(1, _i(page, 1))
    per_page = max(1, min(100, _i(per_page, 50)))
    if not ensure_cycle_journal_db():
        return {"available": False, "page": page, "per_page": per_page, "total": 0, "rows": []}
    offset = (page - 1) * per_page
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*), MIN(cycle), MAX(cycle) FROM lumen_cycle_journal")
                stats = cur.fetchone() or (0, None, None)
                cur.execute(
                    "SELECT cycle, recorded_at, local_time, status, source, payload FROM lumen_cycle_journal ORDER BY cycle DESC LIMIT %s OFFSET %s",
                    (per_page, offset),
                )
                raw = cur.fetchall()
        rows = []
        for cycle, recorded_at, local_time, status, source, payload in raw:
            item = dict(payload or {})
            item.setdefault("cycle", cycle)
            item.setdefault("local_time", local_time)
            item.setdefault("status", status)
            item.setdefault("source", source)
            item["db_recorded_at"] = recorded_at.isoformat() if hasattr(recorded_at, "isoformat") else str(recorded_at)
            rows.append(item)
        total = _i(stats[0])
        return {
            "available": True,
            "page": page,
            "per_page": per_page,
            "total": total,
            "first_cycle": stats[1],
            "last_cycle": stats[2],
            "pages": max(1, (total + per_page - 1) // per_page),
            "rows": rows,
        }
    except Exception as exc:
        return {"available": False, "error": f"{type(exc).__name__}: {str(exc)[:180]}", "page": page, "per_page": per_page, "total": 0, "rows": []}


def _status_class(status: str) -> str:
    return "cj-ok" if status == "HEALTHY" else "cj-warn"


def _cycle_card(row: Dict[str, Any], *, compact: bool = False) -> str:
    decision = row.get("decision", {}) or {}
    research = row.get("research", {}) or {}
    counts = row.get("counts", {}) or {}
    delta = row.get("delta", {}) or {}
    money = row.get("money", {}) or {}
    system = row.get("system", {}) or {}
    blockers = row.get("blockers", []) or []
    cycle = _i(row.get("cycle"))
    head = (
        f"Ciclo {cycle} · {_e(row.get('local_time') or '—')} · "
        f"<span class='{_status_class(str(row.get('status') or ''))}'>{_e(row.get('status') or '—')}</span> · "
        f"{_e(decision.get('company_mode') or '—')} · foco {_e(decision.get('management_department') or '—')}"
    )
    if compact:
        return f"<details class='cj-cycle'><summary>{head}</summary><div class='cj-summary'>{_e(row.get('summary') or '')}</div></details>"

    blocker_html = " · ".join(_e(x) for x in blockers) if blockers else "Sin cuellos de botella críticos adicionales"
    retail = _e(research.get("retail_product") or "—")
    return f"""
    <details class='cj-cycle'>
      <summary>{head}</summary>
      <div class='cj-detail-grid'>
        <div class='cj-box'><b>Meta-LUMEN</b><span>Revenue: {_e(decision.get('revenue_directive') or '—')}</span><span>Prioridad: {_e(decision.get('management_priority') or '—')}</span><span>Controller: {_e(decision.get('controller_mode') or '—')}</span><span>Mejora: {_e(decision.get('self_improvement_primary') or '—')}</span><small>{_e(decision.get('next_action') or '')}</small></div>
        <div class='cj-box'><b>Investigación</b><span>Scout: {_i(research.get('scout_queries'))} búsquedas · +{_i(research.get('new_leads_tick'))} leads</span><span>Presupuesto restante: {_i(research.get('budget_remaining'))}</span><span>Retail: {retail} · {_f(research.get('retail_velocity_score')):.0f}/100</span><span>Ventas públicas reportadas: {_i(research.get('retail_reported_sales')):,}</span></div>
        <div class='cj-box'><b>Embudo</b><span>Verificados: {_i(counts.get('verified_companies'))} · compradores {_i(counts.get('verified_buyers'))} · proveedores {_i(counts.get('verified_suppliers'))}</span><span>Demanda: {_i(counts.get('buyers_with_demand'))} · oportunidades {_i(counts.get('opportunities'))} ({_i(delta.get('opportunities')):+d})</span><span>Ofertas: {_i(counts.get('real_offers'))} · propuestas {_i(counts.get('proposals'))}</span><span>Operaciones reales: {_i(counts.get('real_transactions'))}</span></div>
        <div class='cj-box'><b>Dinero y salud</b><span>Comisión cobrada: {_money(money.get('commission_collected_usd'))}</span><span>Beneficio realizado: {_money(money.get('realized_profit_usd'))}</span><span>Beneficio esperado ajustado: {_money(money.get('risk_adjusted_expected_profit_usd'))}</span><span>COO: {_f(system.get('coo_health_score')):.0f}/100 · fallas {_i(system.get('engine_failures'))}</span></div>
      </div>
      <div class='cj-bottom'><b>Cuellos de botella:</b> {blocker_html}<br><b>Resumen:</b> {_e(row.get('summary') or '')}</div>
    </details>"""


def css() -> str:
    return """
    .cycle-journal-panel{margin:0 0 12px;padding:16px;border:1px solid #2b4b60;border-radius:18px;background:linear-gradient(135deg,#07151d,#0b1e29);box-shadow:0 14px 38px #0006;color:#eaf4f8}.cj-head{display:flex;justify-content:space-between;gap:14px;align-items:center}.cj-eyebrow{font-size:10px;font-weight:900;letter-spacing:.17em;color:#8bd8ff}.cj-head h2{margin:4px 0 2px;font-size:20px}.cj-head p{margin:0;color:#8fa8b6;font-size:12px}.cj-link{background:#d7ff64;color:#08110b!important;text-decoration:none;font-weight:900;padding:10px 13px;border-radius:9px;white-space:nowrap}.cj-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:12px}.cj-stat{padding:9px 10px;border:1px solid #1d3949;border-radius:11px;background:#081720}.cj-stat small,.cj-stat b{display:block}.cj-stat small{color:#718d9d;font-size:9px;text-transform:uppercase;letter-spacing:.1em}.cj-stat b{margin-top:3px}.cj-cycle{border-top:1px solid #173442;padding:8px 0}.cj-cycle:first-of-type{margin-top:10px}.cj-cycle summary{cursor:pointer;font-weight:800;font-size:12px;line-height:1.5}.cj-ok{color:#d7ff64}.cj-warn{color:#ffc76a}.cj-summary{color:#8fa8b6;font-size:11px;padding:8px 3px}.cj-detail-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-top:9px}.cj-box{background:#07141c;border:1px solid #1b394a;border-radius:10px;padding:10px}.cj-box b,.cj-box span,.cj-box small{display:block}.cj-box b{color:#bfeaff;margin-bottom:6px}.cj-box span{font-size:11px;color:#c2d0d7;margin-top:3px}.cj-box small{font-size:10px;color:#75909f;margin-top:6px;line-height:1.4}.cj-bottom{font-size:11px;color:#8fa8b6;padding:9px 2px;line-height:1.5}@media(max-width:820px){.cj-head{align-items:flex-start;flex-direction:column}.cj-stats,.cj-detail-grid{grid-template-columns:1fr 1fr}}@media(max-width:520px){.cj-stats,.cj-detail-grid{grid-template-columns:1fr}}
    """


def render_cycle_journal_panel(state: Dict[str, Any]) -> str:
    data = fetch_cycles(page=1, per_page=6)
    rows = data.get("rows", []) or []
    latest = rows[0] if rows else build_cycle_entry(state, source="live_preview") if _i(state.get("ticks")) > 0 else {}
    if latest:
        research = latest.get("research", {}) or {}
        counts = latest.get("counts", {}) or {}
        money = latest.get("money", {}) or {}
        latest_cycle = _i(latest.get("cycle"))
        stats_html = f"""
          <div class='cj-stat'><small>Último ciclo</small><b>{latest_cycle}</b></div>
          <div class='cj-stat'><small>Presupuesto búsqueda</small><b>{_i(research.get('budget_remaining'))} restantes</b></div>
          <div class='cj-stat'><small>Oportunidades</small><b>{_i(counts.get('opportunities'))}</b></div>
          <div class='cj-stat'><small>Comisión cobrada</small><b>{_money(money.get('commission_collected_usd'))}</b></div>
        """
    else:
        stats_html = "<div class='cj-stat'><small>Estado</small><b>Esperando primer ciclo</b></div>"

    cards = "".join(_cycle_card(x, compact=True) for x in rows)
    if not cards:
        cards = "<div class='cj-summary'>El diario se completará automáticamente al terminar el próximo ciclo.</div>"
    return f"""
    <section class='cycle-journal-panel'>
      <div class='cj-head'><div><div class='cj-eyebrow'>DIARIO DE LUMEN · HISTORIAL DE CICLOS</div><h2>Qué pensó, qué hizo y qué cambió</h2><p>Un registro persistente por cada ciclo autónomo. Hora Argentina.</p></div><a class='cj-link' href='/cycle-journal'>Abrir historial completo</a></div>
      <div class='cj-stats'>{stats_html}</div>
      {cards}
    </section>"""


def inject_cycle_journal(base_html: str, state: Dict[str, Any]) -> str:
    if "cycle-journal-panel" in base_html:
        return base_html
    section = render_cycle_journal_panel(state)
    out = base_html.replace("</head>", "<style>" + css() + "</style></head>", 1)
    return out.replace("<body>", "<body>" + section, 1)


def render_cycle_journal_page(state: Dict[str, Any], *, page: int = 1, per_page: int = 50) -> str:
    data = fetch_cycles(page=page, per_page=per_page)
    rows = data.get("rows", []) or []
    cards = "".join(_cycle_card(x, compact=False) for x in rows) or "<div class='empty'>Todavía no hay ciclos registrados.</div>"
    total = _i(data.get("total"))
    pages = _i(data.get("pages"), 1)
    page = max(1, min(page, pages))
    nav = []
    if page > 1:
        nav.append(f"<a href='/cycle-journal?page={page-1}'>← Más nuevos</a>")
    if page < pages:
        nav.append(f"<a href='/cycle-journal?page={page+1}'>Más antiguos →</a>")
    nav_html = "".join(nav) or "<span>Todo el historial visible en una página.</span>"
    return f"""<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta http-equiv='refresh' content='60'><title>LUMEN · Diario de ciclos</title><style>
    :root{{color-scheme:dark}}*{{box-sizing:border-box}}body{{margin:0;background:#061018;color:#eaf4f8;font-family:Inter,system-ui,-apple-system,sans-serif}}.wrap{{max-width:1180px;margin:auto;padding:28px 18px 70px}}.top{{display:flex;justify-content:space-between;gap:15px;align-items:flex-end;margin-bottom:18px}}.brand{{font-weight:950;letter-spacing:.18em;color:#d7ff64;font-size:12px}}h1{{font-size:clamp(34px,6vw,58px);margin:6px 0;line-height:1}}.lead{{color:#8fa8b6;max-width:760px;line-height:1.5}}.back{{color:#8bd8ff;text-decoration:none;font-weight:800}}.meta{{display:flex;gap:8px;flex-wrap:wrap;margin:15px 0}}.pill{{border:1px solid #28485b;border-radius:999px;padding:7px 10px;color:#b7cad4;font-size:11px}}.nav{{display:flex;justify-content:space-between;gap:10px;margin:16px 0;color:#7893a2}}.nav a{{color:#d7ff64;text-decoration:none;font-weight:800}}.empty{{border:1px dashed #35586d;padding:25px;border-radius:14px;color:#8fa8b6}}{css()}
    .cycle-journal-panel{{display:none}}.cj-cycle{{background:#091720;border:1px solid #1b394a;border-radius:13px;padding:11px 13px;margin:8px 0}}.cj-cycle:first-of-type{{margin-top:0}}@media(max-width:720px){{.top{{align-items:flex-start;flex-direction:column}}}}
    </style></head><body><main class='wrap'><div class='top'><div><div class='brand'>LUMEN · DIARIO AUTÓNOMO</div><h1>Historial de ciclos</h1><p class='lead'>Cada fila corresponde a un ciclo terminado: decisión ejecutiva, investigación, producto detectado, embudo, dinero, salud del sistema y próximo foco. Se actualiza solo.</p></div><a class='back' href='/command-center'>← Command Center</a></div><div class='meta'><span class='pill'>{total} ciclo(s) registrados</span><span class='pill'>Desde ciclo {_e(data.get('first_cycle') or '—')}</span><span class='pill'>Último ciclo {_e(data.get('last_cycle') or '—')}</span><span class='pill'>Página {page}/{pages}</span><span class='pill'>Auto-refresh 60 s</span></div>{cards}<div class='nav'>{nav_html}</div></main></body></html>"""
