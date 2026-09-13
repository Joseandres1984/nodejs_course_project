from __future__ import annotations

import html
from typing import Any, Dict, List


def _e(v: Any) -> str:
    return html.escape(str(v if v is not None else ""), quote=True)


def _i(v: Any) -> int:
    try:
        return int(v)
    except Exception:
        return 0


def _f(v: Any) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0


def snapshot(state: Dict[str, Any]) -> Dict[str, Any]:
    report = dict(state.get("system_watchdog", {}) or {})
    return {
        "report": report,
        "checks": list(report.get("checks", []) or []),
        "history": list(state.get("system_watchdog_history", []) or []),
    }


def _status_label(status: str) -> str:
    return {"pass": "OK", "warn": "ATENCIÓN", "fail": "ERROR"}.get(status, status.upper())


def render_watchdog_strip(state: Dict[str, Any]) -> str:
    s = snapshot(state)
    r = s["report"]
    if not r:
        body = "Sin ejecución todavía"
        score = "—"
        tone = "pending"
    else:
        body = f"{_i(r.get('passed'))}/{_i(r.get('total'))} OK · {_i(r.get('warnings'))} avisos · {_i(r.get('failed'))} errores"
        score = f"{_f(r.get('score_pct')):.0f}%"
        tone = "healthy" if _i(r.get("failed")) == 0 else "degraded"
    return f"""
    <section class='watchdog-strip {tone}'>
      <div><div class='wd-eye'>SYSTEM WATCHDOG · AUTODIAGNÓSTICO</div><h2>LUMEN se prueba a sí mismo en cada ciclo</h2><p>{_e(body)}. Comprueba persistencia, pipeline de captación, creatividades, tracking, Deep Work, plantilla y gates de seguridad.</p></div>
      <div class='wd-score'><small>Salud técnica</small><b>{_e(score)}</b></div>
      <a class='wd-btn' href='/system-test'>Ver diagnóstico</a>
    </section>
    """


def css() -> str:
    return """
    .watchdog-strip{margin:0 0 12px;padding:15px 16px;border:1px solid #28566d;border-radius:17px;background:linear-gradient(135deg,#071923,#102117);display:grid;grid-template-columns:1.5fr auto auto;gap:16px;align-items:center;color:#edf7fb}.watchdog-strip.degraded{border-color:#815038;background:linear-gradient(135deg,#20110a,#141b19)}.watchdog-strip.pending{opacity:.85}.wd-eye{font-size:10px;font-weight:900;letter-spacing:.15em;color:#8bd8ff}.watchdog-strip h2{margin:4px 0;font-size:18px}.watchdog-strip p{margin:0;color:#95aab5;font-size:11px;line-height:1.45}.wd-score{min-width:105px;text-align:center;border:1px solid #2b4c5d;border-radius:12px;background:#08141b;padding:10px}.wd-score small,.wd-score b{display:block}.wd-score small{font-size:9px;text-transform:uppercase;color:#7893a2}.wd-score b{font-size:25px;margin-top:2px;color:#d7ff64}.degraded .wd-score b{color:#ffb47a}.wd-btn{display:block;text-decoration:none;font-weight:900;padding:11px 14px;border-radius:10px;background:#d7ff64;color:#07100a!important;white-space:nowrap;text-align:center}@media(max-width:820px){.watchdog-strip{grid-template-columns:1fr}.wd-score{text-align:left}.wd-btn{width:100%}}
    """


def inject_watchdog_strip(base_html: str, state: Dict[str, Any]) -> str:
    if "watchdog-strip" in base_html:
        return base_html
    out = base_html.replace("</head>", "<style>" + css() + "</style></head>", 1)
    return out.replace("<body>", "<body>" + render_watchdog_strip(state), 1)


def _checks_html(checks: List[Dict[str, Any]]) -> str:
    if not checks:
        return "<div class='empty'>El watchdog todavía no ejecutó un ciclo.</div>"
    out = []
    for idx, row in enumerate(checks, 1):
        status = str(row.get("status") or "warn")
        out.append(
            "<article class='check {status}'>"
            "<div class='num'>{idx:02d}</div>"
            "<div class='copy'><div class='label'>{label}</div><b>{name}</b><p>{detail}</p></div>"
            "</article>".format(
                status=_e(status), idx=idx, label=_e(_status_label(status)), name=_e(row.get("name")), detail=_e(row.get("detail"))
            )
        )
    return "".join(out)


def _history_html(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "<div class='empty'>Todavía no hay historial.</div>"
    out = []
    for row in rows[-20:][::-1]:
        out.append(
            "<div class='hist'><span>{ts}</span><b>{passed}/{total}</b><span>{warnings} avisos</span><span>{failed} errores</span><strong>{score:.0f}%</strong></div>".format(
                ts=_e(row.get("updated_at")), passed=_i(row.get("passed")), total=_i(row.get("total")), warnings=_i(row.get("warnings")), failed=_i(row.get("failed")), score=_f(row.get("score_pct"))
            )
        )
    return "".join(out)


def render_watchdog_page(state: Dict[str, Any]) -> str:
    s = snapshot(state)
    r = s["report"]
    status = str(r.get("status") or "pending")
    passed, total = _i(r.get("passed")), _i(r.get("total"))
    warnings, failed = _i(r.get("warnings")), _i(r.get("failed"))
    score = _f(r.get("score_pct"))
    style = """
    :root{--text:#eef7fb;--muted:#8da5b2;--line:#294b5e;--lime:#d7ff64;--blue:#8bd8ff;--red:#ff8c74;--amber:#ffca7a}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 8% 0,#12344b 0,#061018 38%);color:var(--text);font-family:Inter,system-ui,-apple-system,sans-serif}.wrap{max-width:1180px;margin:auto;padding:26px 18px 70px}.top{display:flex;justify-content:space-between;gap:16px;align-items:end}.brand{color:var(--blue);font-weight:950;letter-spacing:.16em}h1{font-size:40px;margin:8px 0}.sub{color:var(--muted);max-width:820px;line-height:1.5}.back{text-decoration:none;color:#9bdcff;border:1px solid #315467;border-radius:9px;padding:10px 12px;font-weight:900}.hero{display:grid;grid-template-columns:1.2fr repeat(4,1fr);gap:8px;margin:20px 0}.hero>div{border:1px solid var(--line);border-radius:14px;background:#0a1821;padding:13px}.hero small,.hero b{display:block}.hero small{font-size:9px;color:#7893a2;text-transform:uppercase}.hero b{font-size:23px;margin-top:4px}.hero .score b{font-size:36px;color:var(--lime)}.checks{display:grid;grid-template-columns:1fr 1fr;gap:9px}.check{display:grid;grid-template-columns:48px 1fr;gap:10px;border:1px solid #244552;border-radius:14px;background:#091821;padding:12px}.check.pass{border-color:#2d6048}.check.warn{border-color:#715f2c}.check.fail{border-color:#814434}.num{font:800 16px ui-monospace,monospace;color:#668898;padding-top:3px}.label{display:inline-block;font-size:9px;font-weight:950;letter-spacing:.1em;color:#9ee2bd}.warn .label{color:var(--amber)}.fail .label{color:var(--red)}.copy b{display:block;font-size:14px;margin:5px 0}.copy p{margin:0;color:#91a7b3;font-size:11px;line-height:1.5}.history{margin-top:22px;border:1px solid var(--line);border-radius:15px;background:#08161e;padding:10px 14px}.history h2{font-size:16px}.hist{display:grid;grid-template-columns:1.5fr .5fr .7fr .7fr .45fr;gap:8px;padding:9px 0;border-bottom:1px solid #173543;align-items:center}.hist:last-child{border-bottom:0}.hist span{font-size:10px;color:#7f98a6}.hist strong{color:var(--lime);text-align:right}.truth{margin:18px 0;padding:14px;border:1px solid #5a4f20;border-radius:12px;background:#151306;color:#c7ccb1;line-height:1.5;font-size:12px}.empty{padding:20px;color:#7893a2}@media(max-width:900px){.hero{grid-template-columns:1fr 1fr}.checks{grid-template-columns:1fr}.top{flex-direction:column;align-items:flex-start}}@media(max-width:560px){.hero{grid-template-columns:1fr}.hist{grid-template-columns:1fr 1fr}.hist strong{text-align:left}}
    """
    return """<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta http-equiv='refresh' content='45'><title>LUMEN · System Watchdog</title><style>{style}</style></head><body><main class='wrap'><section class='top'><div><div class='brand'>LUMEN · SYSTEM WATCHDOG</div><h1>Prueba continua del sistema</h1><p class='sub'>No confía en que “parezca funcionar”. En cada ciclo ejecuta controles reales y dry-runs aislados para comprobar persistencia, captación, creatividades, distribución, tracking, Deep Work, plantilla y autoridad.</p></div><a class='back' href='/command-center'>← Command Center</a></section><section class='hero'><div class='score'><small>Salud</small><b>{score:.0f}%</b></div><div><small>OK</small><b>{passed}/{total}</b></div><div><small>Avisos</small><b>{warnings}</b></div><div><small>Errores</small><b>{failed}</b></div><div><small>Estado</small><b>{status}</b></div></section><div class='truth'><b>Importante:</b> este diagnóstico demuestra funcionamiento técnico y de los controles internos. La prueba de negocio sigue siendo tráfico real → lead → empresa verificada → oportunidad → operación → comisión.</div><section class='checks'>{checks}</section><section class='history'><h2>Historial reciente</h2>{history}</section></main></body></html>""".format(style=style, score=score, passed=passed, total=total, warnings=warnings, failed=failed, status=_e(status), checks=_checks_html(s["checks"]), history=_history_html(s["history"]))
