from __future__ import annotations

import copy
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

import psycopg


WATCHDOG_VERSION = "1.0"


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _row(check_id: str, name: str, status: str, detail: str, severity: str = "critical") -> Dict[str, Any]:
    return {
        "id": check_id,
        "name": name,
        "status": status,
        "detail": detail[:500],
        "severity": severity,
    }


def _pass(check_id: str, name: str, detail: str) -> Dict[str, Any]:
    return _row(check_id, name, "pass", detail)


def _warn(check_id: str, name: str, detail: str) -> Dict[str, Any]:
    return _row(check_id, name, "warn", detail, "warning")


def _fail(check_id: str, name: str, detail: str) -> Dict[str, Any]:
    return _row(check_id, name, "fail", detail)


def _db_roundtrip() -> tuple[bool, str]:
    url = str(os.getenv("DATABASE_URL") or "").strip()
    if not url:
        return False, "DATABASE_URL no configurada"
    token = "WD-" + uuid.uuid4().hex[:16]
    try:
        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """CREATE TABLE IF NOT EXISTS lumen_watchdog_canary (
                    canary_key TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"""
                )
                cur.execute(
                    """INSERT INTO lumen_watchdog_canary(canary_key,payload,updated_at)
                    VALUES ('runtime',%s,NOW())
                    ON CONFLICT (canary_key) DO UPDATE SET payload=EXCLUDED.payload,updated_at=NOW()""",
                    (token,),
                )
                cur.execute("SELECT payload FROM lumen_watchdog_canary WHERE canary_key='runtime'")
                got = cur.fetchone()
        if not got or str(got[0]) != token:
            return False, "Postgres respondió pero el valor escrito no volvió intacto"
        return True, "escritura + lectura Postgres verificadas"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:260]}"


def _parse_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S UTC", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            dt = datetime.strptime(text, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            continue
    return None


def run_system_watchdog(state: Dict[str, Any], db_status: Dict[str, Any] | None = None) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []
    db_status = db_status or {}

    # 1. Configuration exists.
    checks.append(
        _pass("db_config", "Postgres configurado", "DATABASE_URL presente")
        if os.getenv("DATABASE_URL")
        else _fail("db_config", "Postgres configurado", "DATABASE_URL ausente")
    )

    # 2. Real read/write canary.
    ok, detail = _db_roundtrip()
    checks.append(_pass("db_rw", "Persistencia lectura/escritura", detail) if ok else _fail("db_rw", "Persistencia lectura/escritura", detail))

    # 3. Global state shape.
    core_ok = isinstance(state, dict) and all(isinstance(state.get(k, []), list) for k in ("buyers", "suppliers", "opportunities", "deals"))
    checks.append(_pass("state_shape", "Estado global utilizable", "buyers/suppliers/opportunities/deals con estructura válida") if core_ok else _fail("state_shape", "Estado global utilizable", "estructura base inconsistente"))

    # 4. Worker heartbeat freshness.
    last_tick = _parse_utc(state.get("last_tick"))
    if last_tick:
        age_min = max(0.0, (datetime.now(timezone.utc) - last_tick).total_seconds() / 60.0)
        if age_min <= 35:
            checks.append(_pass("heartbeat", "Worker con pulso reciente", f"último ciclo hace {age_min:.1f} min"))
        elif age_min <= 60:
            checks.append(_warn("heartbeat", "Worker con pulso reciente", f"último ciclo hace {age_min:.1f} min; revisar cron si persiste"))
        else:
            checks.append(_fail("heartbeat", "Worker con pulso reciente", f"último ciclo hace {age_min:.1f} min"))
    else:
        checks.append(_warn("heartbeat", "Worker con pulso reciente", "todavía no hay last_tick verificable"))

    # The next checks use a shadow copy: they exercise the pipeline without polluting live business data.
    shadow = copy.deepcopy(state)
    try:
        from acquisition_campaigns import acquisition_campaign_tick
        acq = dict(acquisition_campaign_tick(shadow) or {})
        active = int(acq.get("campaigns_active") or 0)
        checks.append(_pass("campaigns", "Campañas de captación", f"{active} campañas activas") if active >= 3 else _fail("campaigns", "Campañas de captación", f"solo {active} campañas activas"))
    except Exception as exc:
        acq = {}
        checks.append(_fail("campaigns", "Campañas de captación", f"{type(exc).__name__}: {str(exc)[:220]}"))

    # 6. Tokens + tracking routes.
    variants = [v for c in shadow.get("acquisition_campaigns", []) or [] for v in c.get("variants", []) or []]
    tokens = [str(v.get("token") or "") for v in variants]
    paths = [str(v.get("tracking_path") or "") for v in variants]
    token_ok = len(variants) >= 9 and len(set(tokens)) == len(tokens) and all(tokens) and all(p.startswith("/c/") for p in paths)
    checks.append(_pass("tracking_tokens", "Links atribuibles", f"{len(variants)} variantes con token único") if token_ok else _fail("tracking_tokens", "Links atribuibles", "tokens duplicados, ausentes o rutas inválidas"))

    # 7. Distribution queue is actually produced.
    queue = shadow.get("acquisition_distribution_queue", []) or []
    channels = {str(x.get("channel") or "") for x in queue}
    queue_ok = len(queue) >= 15 and {"owned_market", "email_b2b", "instagram", "facebook", "linkedin_company"}.issubset(channels)
    checks.append(_pass("distribution_queue", "Cola de distribución", f"{len(queue)} entregas preparadas en {len(channels)} canales") if queue_ok else _fail("distribution_queue", "Cola de distribución", f"cola insuficiente: {len(queue)} items / canales {sorted(channels)}"))

    # 8. Creative factory dry-run.
    try:
        from creative_factory import creative_factory_tick
        creative = dict(creative_factory_tick(shadow) or {})
        total_assets = int(creative.get("assets_total") or 0)
        checks.append(_pass("creative_factory", "Creative Factory", f"dry-run generó {total_assets} piezas") if total_assets >= 12 else _fail("creative_factory", "Creative Factory", f"solo {total_assets} piezas generadas"))
    except Exception as exc:
        creative = {}
        checks.append(_fail("creative_factory", "Creative Factory", f"{type(exc).__name__}: {str(exc)[:220]}"))

    # 9. Creative quality gate.
    assets = shadow.get("creative_assets", []) or []
    bad_assets = [x for x in assets if float(x.get("quality_score") or 0) < 70 or not str(x.get("tracking_path") or "").startswith("/c/")]
    checks.append(_pass("creative_quality", "Calidad creativa mínima", f"{len(assets)} piezas con tracking y sin fallas críticas") if assets and not bad_assets else _fail("creative_quality", "Calidad creativa mínima", f"{len(bad_assets)} piezas fuera del gate de calidad"))

    # 10. First-party publication proof works in shadow mode.
    try:
        from distribution_proof import distribution_proof_tick
        proof = dict(distribution_proof_tick(shadow) or {})
        owned = int(proof.get("owned_live") or 0)
        checks.append(_pass("owned_proof", "Prueba de publicación propia", f"{owned} entregas own-channel reconocidas") if owned > 0 else _fail("owned_proof", "Prueba de publicación propia", "no detectó ninguna publicación de canal propio"))
    except Exception as exc:
        proof = {}
        checks.append(_fail("owned_proof", "Prueba de publicación propia", f"{type(exc).__name__}: {str(exc)[:220]}"))

    # 11. Truth gate: external publication cannot be invented.
    ledger = shadow.get("distribution_proof_ledger", []) or []
    external_verified_without_receipt = [
        x for x in ledger
        if x.get("status") == "verified_published" and not (x.get("external_url") or x.get("external_post_id"))
    ]
    waiting_external = [x for x in ledger if x.get("requires_connector") and x.get("status") == "awaiting_authorized_connector"]
    truth_ok = not external_verified_without_receipt and bool(waiting_external)
    checks.append(_pass("truth_gate", "Regla publicada ≠ preparada", f"{len(waiting_external)} externas siguen esperando comprobante real") if truth_ok else _fail("truth_gate", "Regla publicada ≠ preparada", f"{len(external_verified_without_receipt)} publicaciones externas sin evidencia"))

    # 12. Tracking ledgers are available for real traffic.
    tracking_ok = isinstance(state.get("acquisition_events", []), list) and isinstance(state.get("market_reach_events", []), list)
    checks.append(_pass("tracking_ledgers", "Telemetría de clicks/visitas", "ledgers de acquisition y Market disponibles") if tracking_ok else _fail("tracking_ledgers", "Telemetría de clicks/visitas", "estructura de telemetría inválida"))

    # 13. Inbound lead schema / readiness.
    incoming = state.get("acquisition_leads", []) or []
    malformed = [x for x in incoming[-50:] if not x.get("audience") or not x.get("email") or not x.get("status")]
    if malformed:
        checks.append(_fail("lead_intake", "Ingreso de leads", f"{len(malformed)} leads recientes con esquema incompleto"))
    else:
        checks.append(_pass("lead_intake", "Ingreso de leads", f"pipeline listo; {len(incoming)} leads registrados"))

    # 14. Professional case desk exists and is structurally valid.
    cases = state.get("professional_cases", []) or []
    cases_ok = isinstance(cases, list) and all(isinstance(x, dict) and x.get("id") for x in cases[-100:])
    checks.append(_pass("casework", "Deep Work profesional", f"{len(cases)} expedientes persistentes") if cases_ok else _fail("casework", "Deep Work profesional", "estructura de expedientes inválida"))

    # 15. Elastic workforce exists.
    workforce = state.get("agent_workforce", {}) or {}
    roster = workforce.get("roster", []) or []
    if isinstance(workforce, dict) and isinstance(roster, list) and roster:
        checks.append(_pass("workforce", "Plantilla digital", f"{len(roster)} agentes en roster"))
    else:
        checks.append(_warn("workforce", "Plantilla digital", "roster aún no materializado en este estado"))

    # 16. Brokerage constitution remains intact.
    try:
        from operating_constitution import constitutional_doctrine
        doctrine = constitutional_doctrine()
        model = doctrine.get("business_model", {}) or {}
        safe_model = (
            model.get("inventory_owned") is False
            and model.get("buyer_pays_supplier_directly") is True
            and model.get("gross_transaction_funds_received_by_lumen") is False
            and model.get("lumen_revenue") == "commission_or_success_fee_only"
        )
        checks.append(_pass("brokerage_model", "Modelo de intermediación", "sin inventario propio ni custodia del valor bruto") if safe_model else _fail("brokerage_model", "Modelo de intermediación", "la constitución comercial no coincide con el modelo aprobado"))
    except Exception as exc:
        checks.append(_fail("brokerage_model", "Modelo de intermediación", f"{type(exc).__name__}: {str(exc)[:220]}"))

    # 17. Human authority gates remain closed for binding/spend actions.
    meta = state.get("meta_autonomy", {}) or {}
    acq_engine = state.get("acquisition_engine", {}) or {}
    human_gate_ok = (
        meta.get("autonomy_boundary", {}).get("production_code_self_modify") is False
        and str(acq_engine.get("paid_media_policy") or "human_approval_required_for_budget_or_spend") == "human_approval_required_for_budget_or_spend"
    )
    checks.append(_pass("authority_gates", "Gates de autoridad", "código productivo y gasto publicitario siguen bajo aprobación humana") if human_gate_ok else _fail("authority_gates", "Gates de autoridad", "un gate vinculante o de gasto quedó demasiado abierto"))

    passed = sum(1 for x in checks if x["status"] == "pass")
    warnings = sum(1 for x in checks if x["status"] == "warn")
    failed = sum(1 for x in checks if x["status"] == "fail")
    total = len(checks)
    report = {
        "version": WATCHDOG_VERSION,
        "updated_at": utcnow(),
        "status": "healthy" if failed == 0 else "degraded",
        "passed": passed,
        "warnings": warnings,
        "failed": failed,
        "total": total,
        "score_pct": round((passed + warnings * 0.5) / max(1, total) * 100, 1),
        "checks": checks,
        "external_distribution_verified": int((state.get("distribution_proof", {}) or {}).get("external_verified_published") or 0),
        "note": "Este watchdog prueba funcionamiento técnico y gates. El rendimiento comercial se demuestra con tráfico, leads, oportunidades y comisiones reales.",
    }
    state["system_watchdog"] = report
    history = list(state.get("system_watchdog_history", []) or [])
    history.append({k: report[k] for k in ("updated_at", "status", "passed", "warnings", "failed", "total", "score_pct")})
    state["system_watchdog_history"] = history[-100:]
    return report
