import app from "./mobile_layout_fix_worker.js";

function n(v) { return Number(v || 0); }
function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, (m) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[m]));
}
function usd(v) {
  return `USD ${n(v).toLocaleString("es-AR", { maximumFractionDigits: 2 })}`;
}
function event(title, sub, more = "") {
  return `<div class="ntEvent"><strong>${esc(title || "—")}</strong><div class="small ntMuted">${esc(sub || "")}</div>${more ? `<div class="small">${esc(more)}</div>` : ""}</div>`;
}
function members(raw) {
  try {
    const x = JSON.parse(raw || "[]");
    return Array.isArray(x) ? x.slice(0, 4).map((m) => `${m.name || "agente"} · ${m.role || "rol"}`).join(" | ") : "";
  } catch { return ""; }
}
function chip(v, kind = "") {
  return `<span class="ntChip ${kind}">${esc(v)}</span>`;
}

async function networkSnapshot(request, env, ctx) {
  try {
    const url = new URL(request.url);
    url.pathname = "/api/network-control-v1";
    url.search = "";
    const response = await app.fetch(new Request(url.toString(), {
      method: "GET",
      headers: request.headers,
    }), env, ctx);
    if (!response.ok) return null;
    return await response.json();
  } catch {
    return null;
  }
}

function setPanel(html, id, content) {
  const empty = `<div id="${id}"></div>`;
  return html.includes(empty) ? html.replace(empty, `<div id="${id}">${content}</div>`) : html;
}
function setClassPanel(html, cls, id, content) {
  const empty = `<div class="${cls}" id="${id}"></div>`;
  return html.includes(empty) ? html.replace(empty, `<div class="${cls}" id="${id}">${content}</div>`) : html;
}

function hydratePanels(html, data) {
  if (!data) {
    const unavailable = '<div class="empty">Datos de red no disponibles en este momento.</div>';
    for (const id of ["ntRoomsList", "ntTasksList", "ntNegotiatorList", "ntReferralList", "ntVentureList", "ntGapList", "ntTeamList", "ntGraphList"]) {
      html = setPanel(html, id, unavailable);
    }
    html = setClassPanel(html, "ntTable", "ntEconomyList", unavailable);
    html = setClassPanel(html, "ntGuard", "ntGuardrails", '<div><strong>Guardrails</strong><div class="small">No se pudo leer el estado vivo. Las restricciones de seguridad no se relajan por este error visual.</div></div>');
    return html;
  }

  const rooms = Array.isArray(data.rooms) ? data.rooms : [];
  html = setPanel(html, "ntRoomsList", rooms.length
    ? rooms.map((x) => event(`${x.id} · ${x.status}`, `Ronda ${n(x.round_no)} · ${n(x.contributions)}/${n(x.members)} contribuciones`, `Alineación ${x.alignment_score == null ? "—" : n(x.alignment_score)} · mensajes externos ${n(x.external_messages)}`)).join("")
    : '<div class="empty">Sin salas creadas.</div>');

  const tasks = Array.isArray(data.tasks) ? data.tasks : [];
  html = setPanel(html, "ntTasksList", tasks.length
    ? tasks.map((x) => event(`${x.partner_name || "Agente"} · ${x.role || "rol"}`, `${x.status || "—"} · ${x.title || ""}`, `${x.quality_score == null ? "" : `Quality ${n(x.quality_score)}`}${x.error ? ` · ${x.error}` : ""}`)).join("")
    : '<div class="empty">Sin tareas de delegación todavía.</div>');

  const negotiations = Array.isArray(data.negotiations) ? data.negotiations : [];
  html = setPanel(html, "ntNegotiatorList", negotiations.length
    ? negotiations.map((x) => event(x.title, `${x.status || "—"} · ${n(x.candidate_count)} candidatos · ${n(x.priced_candidate_count)} precios`, `Recomendado: ${x.recommended_partner_name || "aún no"} · confidence ${n(x.recommendation_confidence)}`)).join("")
    : '<div class="empty">Sin casos de negociación.</div>');

  const referrals = Array.isArray(data.referralRows) ? data.referralRows : [];
  html = setPanel(html, "ntReferralList", referrals.length
    ? referrals.map((x) => event(x.title, `${x.direction || ""} · ${x.status || ""}`, `${x.target_partner_name || x.origin_partner_name ? `Agente: ${x.target_partner_name || x.origin_partner_name} · ` : ""}match ${n(x.match_score)} · settled ${usd(x.settled_revenue_usd)}`)).join("")
    : '<div class="empty">Sin referrals.</div>');

  const ventures = Array.isArray(data.ventures) ? data.ventures : [];
  html = setPanel(html, "ntVentureList", ventures.length
    ? ventures.map((x) => event(x.title, `${x.status || "—"} · readiness ${n(x.readiness_score)} · coverage ${n(x.coverage_score)}`, `gaps ${n(x.gap_count)} · ${x.next_experiment || ""}`)).join("")
    : '<div class="empty">Todavía no hay Venture Cases maduros.</div>');

  const gaps = Array.isArray(data.gapRows) ? data.gapRows : [];
  html = setPanel(html, "ntGapList", gaps.length
    ? gaps.map((x) => event(x.capability, `Prioridad ${n(x.priority)} · ${x.status || "—"}`, `Candidatos ${n(x.current_candidates)} · fuertes ${n(x.strong_candidates)} · mejor ${x.best_partner_name || "ninguno"}`)).join("")
    : '<div class="empty">No hay gaps abiertos.</div>');

  const teams = Array.isArray(data.teams) ? data.teams : [];
  html = setPanel(html, "ntTeamList", teams.length
    ? teams.map((x) => event(x.id, `Score ${n(x.team_score)} · coverage ${n(x.coverage_score)} · affinity ${n(x.graph_affinity_score)}`, members(x.members_json))).join("")
    : '<div class="empty">Sin equipos dinámicos activos.</div>');

  const edges = Array.isArray(data.graphEdges) ? data.graphEdges : [];
  html = setPanel(html, "ntGraphList", edges.length
    ? edges.map((x) => event(`${x.source_name || "Agente"} + ${x.target_name || "Agente"}`, `${x.relation_type || "—"} · affinity ${n(x.affinity_score)}`, `contextos ${n(x.contexts)} · éxitos ${n(x.successes)} · fallas ${n(x.failures)}`)).join("")
    : '<div class="empty">Sin historial conjunto suficiente.</div>');

  const intents = Array.isArray(data.economyIntents) ? data.economyIntents : [];
  const economy = intents.length
    ? `<table><thead><tr><th>Dirección</th><th>Servicio</th><th>Contraparte</th><th>USD</th><th>Estado</th><th>Aprobación</th><th>Settlement</th></tr></thead><tbody>${intents.map((x) => `<tr><td>${chip(x.direction, x.direction === "INCOME" ? "ntGood" : "ntWarn")}</td><td>${esc(x.service_name || x.kind || "—")}</td><td>${esc(x.counterparty_name || "—")}</td><td>${usd(x.amount_usd)}</td><td>${esc(x.status || "—")}</td><td>${esc(x.approval_status || "—")}</td><td>${esc(x.settlement_status || "—")}${n(x.settled_amount_usd) > 0 ? ` · ${usd(x.settled_amount_usd)}` : ""}</td></tr>`).join("")}</tbody></table>`
    : '<div class="empty">Sin intenciones económicas registradas.</div>';
  html = setClassPanel(html, "ntTable", "ntEconomyList", economy);

  const guardrails = '<div><strong>Gasto autónomo</strong><div class="ntKpi">USD 0</div><div class="small">hard-blocked</div></div><div><strong>Contratos automáticos</strong><div class="ntKpi">NO</div><div class="small">human-gated</div></div><div><strong>Compras autónomas</strong><div class="ntKpi">NO</div><div class="small">human-gated</div></div><div><strong>Ingreso realizado</strong><div class="ntKpi">SETTLED</div><div class="small">sólo pago verificado</div></div><div><strong>Trust</strong><div class="ntKpi">OBLIGATORIO</div><div class="small">antes de acciones externas sensibles</div></div><div><strong>Calidad</strong><div class="ntKpi">GATES</div><div class="small">juntas, tareas, resultados y propuestas</div></div>';
  html = setClassPanel(html, "ntGuard", "ntGuardrails", guardrails);
  return html;
}

export default {
  async fetch(request, env, ctx) {
    const response = await app.fetch(request, env, ctx);
    const url = new URL(request.url);
    const isDashboardPage = request.method === "GET"
      && response.ok
      && ["/", "/index.html", "/full", "/secretaria", "/secretaria/"].includes(url.pathname)
      && String(response.headers.get("content-type") || "").includes("text/html");
    if (!isDashboardPage) return response;

    let html = await response.text();
    const snapshot = await networkSnapshot(request, env, ctx);
    html = hydratePanels(html, snapshot);

    const headers = new Headers(response.headers);
    headers.delete("content-length");
    headers.set("cache-control", "no-store, no-cache, must-revalidate");
    headers.set("x-lumen-network-panel-hydration", snapshot ? "live" : "fallback");
    return new Response(html, { status: response.status, statusText: response.statusText, headers });
  },
};
