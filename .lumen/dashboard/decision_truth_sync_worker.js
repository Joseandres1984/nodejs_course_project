import app from "./unified_decision_center_worker.js";

const CHANNEL_TRUTH_SCRIPT = `<script id="lumenChannelTruthPatch">
(() => {
  let lastMailReady = null;
  let scheduled = false;

  function alertRow() {
    const channels = document.getElementById('channels');
    if (!channels) return null;
    let row = [...channels.querySelectorAll('.statusline')].find((candidate) => {
      const label = candidate.querySelector('span');
      return (label?.textContent || '').trim() === 'Alertas internas';
    });
    if (!row) {
      channels.insertAdjacentHTML('beforeend', '<div class="statusline"><span>Alertas internas</span><strong></strong></div>');
      row = [...channels.querySelectorAll('.statusline')].find((candidate) => {
        const label = candidate.querySelector('span');
        return (label?.textContent || '').trim() === 'Alertas internas';
      });
    }
    return row || null;
  }

  function applyTruth() {
    if (lastMailReady === null) return;
    const row = alertRow();
    const value = row?.querySelector('strong');
    if (!value) return;
    const desired = lastMailReady
      ? '<span class="chip ok">EMAIL + PANEL</span>'
      : '<span class="chip">PANEL · EMAIL NO DISPONIBLE</span>';
    if (value.innerHTML !== desired) value.innerHTML = desired;
  }

  function scheduleApply() {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => {
      scheduled = false;
      applyTruth();
    });
  }

  async function refreshChannelTruth() {
    try {
      const response = await fetch('/api/data?_=' + Date.now(), {
        cache: 'no-store',
        headers: { Accept: 'application/json' },
      });
      if (!response.ok) throw new Error('HTTP ' + response.status);
      const data = await response.json();
      lastMailReady = data?.outbound?.mail_ready === true;
    } catch {
      // Fail closed: never advertise email readiness when live truth cannot be read.
      lastMailReady = false;
    }
    applyTruth();
  }

  const observer = new MutationObserver(scheduleApply);
  observer.observe(document.body, { subtree: true, childList: true, characterData: true });
  refreshChannelTruth();

  document.addEventListener('click', (event) => {
    if (event.target?.id === 'lumenRefreshBtn') {
      window.setTimeout(refreshChannelTruth, 250);
    }
  });
})();
</script>`;

function patchChannelTruth(html) {
  if (html.includes('id="lumenChannelTruthPatch"')) return html;
  return html.includes('</body>')
    ? html.replace('</body>', CHANNEL_TRUTH_SCRIPT + '</body>')
    : html + CHANNEL_TRUTH_SCRIPT;
}

async function commercialDecisionCommands(env) {
  try {
    const result = await env.DB.prepare(
      "SELECT decision_key,object_id,action,processed,processed_at,result FROM lumen_owner_decision_commands WHERE decision_type='commercial_close' ORDER BY created_at DESC"
    ).all();
    return result.results || [];
  } catch {
    return [];
  }
}

function syncCommercialDecisionTruth(data, commands) {
  const rows = Array.isArray(commands) ? commands : [];
  const decidedIds = new Set(rows.map((row) => String(row?.object_id || "")).filter(Boolean));
  const sourceApprovals = Array.isArray(data?.approvals) ? data.approvals : [];
  const pendingApprovals = sourceApprovals.filter((approval) => !decidedIds.has(String(approval?.id || "")));
  const processing = rows.filter((row) => Number(row?.processed || 0) === 0).length;
  const processed = rows.filter((row) => Number(row?.processed || 0) === 1).length;

  data.money = data.money && typeof data.money === "object" ? data.money : {};
  data.money.pending_closures = pendingApprovals.length;
  data.money.decision_commands_processing = processing;
  data.money.decision_commands_processed = processed;
  data.approvals = pendingApprovals;
  data.decision_truth = {
    source: "lumen_owner_decision_commands",
    pending_human_decisions: pendingApprovals.length,
    commands_processing: processing,
    commands_processed: processed,
    synchronized: true,
  };
  return data;
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const upstream = await app.fetch(request, env, ctx);

    if (upstream.status === 401 || upstream.status === 503) return upstream;

    if (request.method === "GET" && url.pathname === "/api/data" && String(upstream.headers.get("content-type") || "").includes("application/json")) {
      try {
        const data = await upstream.json();
        const commands = await commercialDecisionCommands(env);
        const synced = syncCommercialDecisionTruth(data, commands);
        const headers = new Headers(upstream.headers);
        headers.delete("content-length");
        headers.set("cache-control", "no-store");
        headers.set("x-lumen-decision-truth-sync", "v1");
        return new Response(JSON.stringify(synced), { status: upstream.status, headers });
      } catch (error) {
        return new Response(JSON.stringify({ ok: false, error: "decision_truth_sync_failed", detail: String(error?.message || error).slice(0, 240) }), {
          status: 500,
          headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
        });
      }
    }

    const contentType = String(upstream.headers.get("content-type") || "");
    if (request.method === "GET" && upstream.ok && contentType.includes("text/html")) {
      const html = patchChannelTruth(await upstream.text());
      const headers = new Headers(upstream.headers);
      headers.delete("content-length");
      headers.set("cache-control", "no-store, no-cache, must-revalidate, max-age=0");
      headers.set("pragma", "no-cache");
      headers.set("x-lumen-mail-ui-truth", "v1");
      return new Response(html, { status: upstream.status, headers });
    }

    return upstream;
  },
};
