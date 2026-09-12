from __future__ import annotations

import html
import json
from typing import Any, Dict, List


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _money(value: Any) -> str:
    try:
        return f"USD {float(value):,.0f}"
    except (TypeError, ValueError):
        return "USD 0"


def _severity_rank(value: Any) -> int:
    return {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(str(value or ""), 0)


def build_cockpit(state: Dict[str, Any]) -> Dict[str, Any]:
    alerts = [x for x in state.get("executive_alerts", []) or [] if x.get("status") == "open"]
    alerts.sort(key=lambda x: (_severity_rank(x.get("severity")), bool(x.get("action_required")), str(x.get("last_seen_at") or "")), reverse=True)

    approvals: List[Dict[str, Any]] = []
    for alert in alerts:
        if alert.get("kind") != "binding_approval" or not alert.get("approval_id"):
            continue
        metrics = alert.get("metrics", {}) or {}
        approvals.append({
            "alert_id": alert.get("id"),
            "approval_id": alert.get("approval_id"),
            "deal_id": alert.get("object_id"),
            "title": alert.get("title"),
            "message": alert.get("message"),
            "recommendation": alert.get("recommendation"),
            "severity": alert.get("severity"),
            "ready": bool(metrics.get("ready_to_decide")),
            "company_profit": _f(metrics.get("company_profit")),
            "company_share_pct": _f(metrics.get("company_share_pct")),
            "close_probability_pct": _f(metrics.get("close_probability_pct")),
            "sale_price": metrics.get("sale_price"),
            "supplier_cost": metrics.get("supplier_cost"),
            "preclose_missing": list(metrics.get("preclose_missing") or []),
            "risk_flags": list(metrics.get("risk_flags") or []),
        })

    nonapproval = [x for x in alerts if x.get("kind") != "binding_approval"]
    return {
        "open_alerts": len(alerts),
        "critical_alerts": sum(1 for x in alerts if x.get("severity") == "critical"),
        "action_required": sum(1 for x in alerts if x.get("action_required")),
        "approvals": approvals[:8],
        "other_alerts": nonapproval[:8],
        "all_alerts": alerts[:12],
    }


def _approval_card(item: Dict[str, Any]) -> str:
    missing = item.get("preclose_missing", []) or []
    risks = item.get("risk_flags", []) or []
    ready = bool(item.get("ready"))
    status = "LISTO PARA DECIDIR" if ready else "NO APROBABLE TODAVÍA"
    status_class = "readytag" if ready else "blockedtag"
    controls = (
        '<span class="cockpit-ok">0 controles faltantes</span>'
        if not missing else
        '<span class="cockpit-warn">Faltan: ' + _esc(", ".join(str(x) for x in missing[:6])) + '</span>'
    )
    risk_html = "".join(f'<span class="riskpill">{_esc(x)}</span>' for x in risks[:5]) or '<span class="riskpill ok">sin flags adicionales</span>'
    buttons = ""
    if ready:
        buttons += (
            f'<form method="post" action="/api/executive-decision" class="inlineform" onsubmit="return confirm(\'¿Aprobar este caso? Esto registra autorización interna; NO ejecuta pagos, contratos ni órdenes reales.\')">'
            f'<input type="hidden" name="approval_id" value="{_esc(item.get("approval_id"))}">'
            '<input type="hidden" name="decision" value="approve">'
            '<button class="approve" type="submit">APROBAR</button></form>'
        )
    buttons += (
        f'<form method="post" action="/api/executive-decision" class="inlineform" onsubmit="return confirm(\'¿Rechazar este cierre y devolverlo a revisión?\')">'
        f'<input type="hidden" name="approval_id" value="{_esc(item.get("approval_id"))}">'
        '<input type="hidden" name="decision" value="reject">'
        '<button class="reject" type="submit">RECHAZAR</button></form>'
    )
    return f'''
    <div class="approvalcase {'readycase' if ready else 'blockedcase'}">
      <div class="casehead"><div><div class="casetag {status_class}">{status}</div><div class="casetitle">{_esc(item.get('deal_id') or item.get('approval_id'))}</div></div><div class="caseprofit">{_money(item.get('company_profit'))}</div></div>
      <div class="casegrid">
        <div><span>Margen</span><b>{_f(item.get('company_share_pct')):.1f}%</b></div>
        <div><span>Prob. cierre</span><b>{_f(item.get('close_probability_pct')):.0f}%</b></div>
        <div><span>Venta</span><b>{_money(item.get('sale_price'))}</b></div>
        <div><span>Costo proveedor</span><b>{_money(item.get('supplier_cost'))}</b></div>
      </div>
      <div class="casemsg">{_esc(item.get('message'))}</div>
      <div class="recommend"><b>Recomendación LUMEN:</b> {_esc(item.get('recommendation'))}</div>
      <div class="controls">{controls}</div><div class="risks">{risk_html}</div>
      <div class="caseactions">{buttons}<span class="actionnote">Aprobar nunca ejecuta una obligación financiera real por sí solo.</span></div>
    </div>'''


def render_cockpit_section(cockpit: Dict[str, Any]) -> str:
    approvals = cockpit.get("approvals", []) or []
    alerts = cockpit.get("other_alerts", []) or []
    approval_html = "".join(_approval_card(x) for x in approvals)
    if not approval_html:
        approval_html = '<div class="cockpit-empty">No hay cierres esperando tu autorización. LUMEN sigue trabajando por defecto.</div>'

    alert_html = ""
    for alert in alerts:
        sev = str(alert.get("severity") or "medium")
        alert_html += (
            f'<div class="execalert {sev}"><div class="alertsev">{_esc(sev.upper())}</div>'
            f'<div><b>{_esc(alert.get("title"))}</b><div class="alertmsg">{_esc(alert.get("message"))}</div>'
            f'<div class="alertrec">{_esc(alert.get("recommendation"))}</div></div></div>'
        )
    if not alert_html:
        alert_html = '<div class="cockpit-empty">Sin alertas ejecutivas adicionales.</div>'

    return f'''
    <section class="cockpit-wrap">
      <div class="cockpit-top"><div><div class="cockpit-eyebrow">APPROVAL COCKPIT</div><h1>Dirigir por excepción</h1><p>LUMEN opera solo. Acá aparecen únicamente decisiones o eventos que justifican interrumpirte.</p></div>
      <div class="cockpit-stats"><div><b>{int(cockpit.get('open_alerts') or 0)}</b><span>alertas abiertas</span></div><div><b>{int(cockpit.get('critical_alerts') or 0)}</b><span>críticas</span></div><div><b>{int(cockpit.get('action_required') or 0)}</b><span>requieren acción</span></div></div></div>
      <div class="cockpit-columns"><div><h2>Decisiones de cierre</h2>{approval_html}</div><div><h2>Executive Alerts</h2>{alert_html}<button id="enable-notifications" class="notifybtn" type="button">Activar avisos del navegador</button><div class="notifynote">Los avisos del navegador funcionan cuando el navegador permite notificaciones. Para alertas fuera del panel podremos conectar un canal ejecutivo dedicado.</div></div></div>
    </section>'''


def cockpit_css() -> str:
    return '''
    .cockpit-wrap{margin:0 0 12px;padding:18px;background:linear-gradient(135deg,#101b11,#0b1720 48%,#111522);border:1px solid #39512e;border-radius:19px;box-shadow:0 18px 46px #0007}.cockpit-top{display:flex;justify-content:space-between;gap:18px;align-items:flex-end}.cockpit-eyebrow{font-size:10px;letter-spacing:.18em;color:#d7ff64;font-weight:900}.cockpit-top h1{margin:5px 0 4px;font-size:23px}.cockpit-top p{margin:0;color:#9db1bc;max-width:720px}.cockpit-stats{display:flex;gap:8px}.cockpit-stats>div{min-width:92px;padding:10px;border:1px solid #294337;border-radius:12px;text-align:center;background:#08130f}.cockpit-stats b{display:block;font-size:20px;color:#d7ff64}.cockpit-stats span{font-size:10px;color:#91a69b}.cockpit-columns{display:grid;grid-template-columns:1.35fr .65fr;gap:12px;margin-top:15px}.cockpit-columns h2{font-size:14px;margin:0 0 10px}.approvalcase{border:1px solid #445344;border-radius:14px;padding:14px;margin:9px 0;background:#0a1513}.approvalcase.readycase{border-color:#46775a;background:#0b1a13}.approvalcase.blockedcase{border-color:#695b32;background:#19170e}.casehead{display:flex;justify-content:space-between;gap:12px;align-items:center}.casetag{font-size:9px;font-weight:900;letter-spacing:.1em;margin-bottom:4px}.readytag{color:#7ce7b3}.blockedtag{color:#ffd36a}.casetitle{font-size:18px;font-weight:850}.caseprofit{font-size:23px;font-weight:900;color:#d7ff64}.casegrid{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:11px}.casegrid>div{padding:8px;background:#07110f;border-radius:8px}.casegrid span{display:block;color:#769187;font-size:9px;text-transform:uppercase}.casegrid b{font-size:13px}.casemsg{color:#b8c9c0;line-height:1.45;margin-top:10px}.recommend{margin-top:9px;padding:9px;border-left:3px solid #d7ff64;background:#111b0e;color:#dce8d5}.controls,.risks{margin-top:8px}.cockpit-ok{color:#7ce7b3}.cockpit-warn{color:#ffd36a}.riskpill{display:inline-block;font-size:10px;padding:4px 7px;border:1px solid #5f4a36;border-radius:99px;margin:2px;color:#e4c8a7}.riskpill.ok{border-color:#315d48;color:#7ce7b3}.caseactions{display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin-top:11px}.inlineform{display:inline}.approve,.reject,.notifybtn{border:0;border-radius:8px;padding:9px 13px;font-weight:900;cursor:pointer}.approve{background:#d7ff64;color:#0a1008}.reject{background:#3b1919;color:#ffb4b4;border:1px solid #703333}.actionnote{font-size:10px;color:#769187}.execalert{display:grid;grid-template-columns:68px 1fr;gap:10px;padding:10px;border-radius:11px;border:1px solid #30414a;margin:8px 0;background:#0b151b}.execalert.critical{border-color:#7a3535}.execalert.high{border-color:#70562e}.alertsev{font-size:9px;font-weight:900;letter-spacing:.08em;color:#ffd36a}.execalert.critical .alertsev{color:#ff8c8c}.alertmsg{font-size:12px;color:#b8cad4;margin-top:3px}.alertrec{font-size:10px;color:#7f9aaa;margin-top:5px}.cockpit-empty{padding:16px;border:1px dashed #315d48;border-radius:11px;color:#7ce7b3}.notifybtn{margin-top:10px;background:#173141;color:#bfe7fa;border:1px solid #2b5770}.notifynote{font-size:10px;color:#6f8997;margin-top:6px}@media(max-width:900px){.cockpit-top{align-items:flex-start;flex-direction:column}.cockpit-columns{grid-template-columns:1fr}.casegrid{grid-template-columns:1fr 1fr}.cockpit-stats{width:100%;overflow:auto}}
    '''


def browser_alert_script(cockpit: Dict[str, Any]) -> str:
    alerts = [
        {"id": x.get("id"), "severity": x.get("severity"), "title": x.get("title"), "message": x.get("message")}
        for x in cockpit.get("all_alerts", []) or []
        if x.get("id") and x.get("status") == "open"
    ]
    payload = json.dumps(alerts, ensure_ascii=False).replace("</", "<\\/")
    return f'''<script>
    (() => {{
      const alerts = {payload};
      const key = 'lumen_exec_alert_ids_v1';
      const seen = new Set(JSON.parse(localStorage.getItem(key) || '[]'));
      function notifyNew() {{
        if (!('Notification' in window) || Notification.permission !== 'granted') return;
        const next = alerts.filter(a => !seen.has(a.id));
        next.slice(0,3).forEach(a => {{ try {{ new Notification('LUMEN · ' + a.title, {{body:a.message, tag:a.id}}); }} catch(e) {{}} seen.add(a.id); }});
        localStorage.setItem(key, JSON.stringify(Array.from(seen).slice(-100)));
      }}
      const btn = document.getElementById('enable-notifications');
      if (btn) btn.addEventListener('click', async () => {{
        if (!('Notification' in window)) {{ btn.textContent='Notificaciones no compatibles'; return; }}
        const permission = await Notification.requestPermission();
        btn.textContent = permission === 'granted' ? 'Avisos activados' : 'Avisos no autorizados';
        notifyNew();
      }});
      notifyNew();
    }})();
    </script>'''


def inject_cockpit(base_html: str, cockpit: Dict[str, Any]) -> str:
    section = render_cockpit_section(cockpit)
    css = '<style>' + cockpit_css() + '</style>'
    script = browser_alert_script(cockpit)
    out = base_html.replace('</head>', css + '</head>', 1)
    marker = '<div class="grid hero">'
    if marker in out:
        out = out.replace(marker, section + marker, 1)
    else:
        out = out.replace('<body>', '<body>' + section, 1)
    return out.replace('</body>', script + '</body>', 1)
