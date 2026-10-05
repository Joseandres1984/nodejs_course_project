import base from "./decision_truth_sync_worker.js";

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

export default {
  async fetch(request, env, ctx) {
    const response = await base.fetch(request, env, ctx);
    const contentType = response.headers.get('content-type') || '';
    if (request.method !== 'GET' || !response.ok || !contentType.includes('text/html')) {
      return response;
    }

    const html = patchChannelTruth(await response.text());
    const headers = new Headers(response.headers);
    headers.set('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0');
    headers.set('Pragma', 'no-cache');
    headers.set('X-Lumen-Mail-UI-Truth', 'v1');
    return new Response(html, { status: response.status, headers });
  },
};
