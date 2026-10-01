import app from "./travel_conversion_panel_worker.js";

const TEACHING_CSS = `<style>
.teacher{margin:0 0 12px;background:linear-gradient(180deg,#101b19,#0a1617);border:1px solid #365143;border-radius:16px;padding:14px;box-shadow:0 14px 35px #0003}.teacher-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;margin-bottom:10px}.teacher-title{font-size:16px;font-weight:950}.teacher-copy{color:#9fb2aa;font-size:12px;line-height:1.5;margin-top:4px;max-width:720px}.teacher-grid{display:grid;grid-template-columns:1.25fr .75fr;gap:10px}.teach-types{display:flex;flex-wrap:wrap;gap:7px;margin-bottom:9px}.teach-type{background:#0c2020;color:#dceee7;border:1px solid #31544b;border-radius:999px;padding:8px 10px;cursor:pointer;font-weight:800}.teach-type.active{background:#d9ff65;color:#061019;border-color:#e7ff9e}.teachbox{width:100%;min-height:82px;resize:vertical;background:#061019;color:#edf5f7;border:1px solid #2c4b47;border-radius:11px;padding:11px;font:inherit;outline:none}.teachbox:focus{border-color:#6d927c;box-shadow:0 0 0 2px #395d4866}.teach-actions{display:flex;gap:8px;align-items:center;margin-top:8px;flex-wrap:wrap}.teach-send,.critic-run{border:0;border-radius:10px;padding:10px 13px;font-weight:950;cursor:pointer}.teach-send{background:#d9ff65;color:#061019}.critic-run{background:#153341;color:#d9edf5;border:1px solid #315a6a}.teach-send:disabled,.critic-run:disabled{opacity:.5;cursor:wait}.teacher-state{background:#08151a;border:1px solid #263f42;border-radius:12px;padding:11px;min-height:100%}.teacher-status{font-weight:850;line-height:1.45;margin-top:5px}.teacher-detail{font-size:11px;color:#90a8aa;line-height:1.5;margin-top:6px}.critic-verdict{color:#ffd98a}.supported{color:#9de8c5}.contradicted{color:#ff9992}.provisional{color:#83d9ff}@media(max-width:700px){.teacher-grid{grid-template-columns:1fr}.teacher-head{display:block}.teacher{padding:11px}}
</style>`;

const TEACHING_HTML = `<section class="teacher" id="teacher-panel"><div class="teacher-head"><div><div class="teacher-title">Modo enseñanza</div><div class="teacher-copy">Podés enseñarle a LUMEN desde acá. Tu aporte entra como una hipótesis provisional: LUMEN lo contrasta con resultados reales antes de cambiar sus preferencias.</div></div><div class="kl">Profesor Humano + Self-Critic</div></div><div class="teacher-grid"><div><div class="teach-types"><button type="button" class="teach-type" data-teach="PRAISE">Esto funcionó</button><button type="button" class="teach-type active" data-teach="SUGGEST">Probá esto</button><button type="button" class="teach-type" data-teach="CORRECT">Corregir decisión</button><button type="button" class="teach-type" data-teach="PRINCIPLE">Guardar principio</button><button type="button" class="teach-type" data-teach="WARNING">Advertencia</button></div><textarea id="teachInput" class="teachbox" maxlength="1200" placeholder="Ej.: Antes de buscar más oportunidades, revisá si las 32 propuestas existentes tienen un seguimiento concreto y medible."></textarea><div class="teach-actions"><button type="button" class="teach-send" id="teachSend">Enseñar a LUMEN</button><button type="button" class="critic-run" id="criticRun">Autocrítica ahora</button><span class="teacher-detail" id="teachHint">Tipo: SUGGEST · la evidencia decide si se incorpora.</span></div></div><div class="teacher-state"><div class="kl">Última revisión crítica</div><div class="teacher-status critic-verdict" id="criticVerdict">Esperando revisión…</div><div class="teacher-detail" id="criticReason">LUMEN cuestionará su táctica si aparece estancamiento, evidencia negativa o un challenger mejor.</div><div class="kl" style="margin-top:12px">Tu enseñanza</div><div class="teacher-status" id="teachStatus">Todavía no enviaste feedback en esta sesión.</div><div class="teacher-detail" id="teachEvidence"></div></div></div></section>`;

const TEACHING_SCRIPT = `<script>
(()=>{const byId=id=>document.getElementById(id);let teachType='SUGGEST';const labels={PRAISE:'Esto funcionó',SUGGEST:'Probá esto',CORRECT:'Corregir decisión',PRINCIPLE:'Guardar principio',WARNING:'Advertencia'};const statusClass=s=>String(s||'').toLowerCase()==='supported'?'supported':String(s||'').toLowerCase()==='contradicted'?'contradicted':'provisional';async function tfetch(url,opts={},timeout=12000){const c=new AbortController(),t=setTimeout(()=>c.abort(),timeout);try{const r=await fetch(url,{...opts,signal:c.signal,cache:'no-store'}),text=await r.text();let d={};try{d=text?JSON.parse(text):{}}catch{throw new Error('Respuesta inválida')}if(!r.ok||d.ok===false)throw new Error(d.error||('HTTP '+r.status));return d}finally{clearTimeout(t)}}function setType(type){teachType=type;document.querySelectorAll('[data-teach]').forEach(b=>b.classList.toggle('active',b.dataset.teach===type));byId('teachHint').textContent='Tipo: '+type+' · la evidencia decide si se incorpora.'}document.querySelectorAll('[data-teach]').forEach(b=>b.addEventListener('click',()=>setType(b.dataset.teach)));async function loadCritic(){try{const d=await tfetch('/api/lumen-self-critic');const c=d.critic||{};if(c.verdict){byId('criticVerdict').textContent=c.verdict+' · '+(c.severity||'INFO');const rec=c.recommendation||{};byId('criticReason').textContent=rec.reason||rec.whatWouldChangeMyMind||'Revisión registrada.'}}catch(e){byId('criticVerdict').textContent='Sin revisión disponible';byId('criticReason').textContent=String(e.message||e)}}async function teach(){const input=byId('teachInput'),message=String(input.value||'').trim(),btn=byId('teachSend');if(!message){byId('teachStatus').className='teacher-status contradicted';byId('teachStatus').textContent='Escribí qué querés enseñarle a LUMEN.';return}btn.disabled=true;try{const d=await tfetch('/api/lumen-teacher-feedback',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({feedbackType:teachType,message})});byId('teachStatus').className='teacher-status '+statusClass(d.status);byId('teachStatus').textContent=(labels[teachType]||teachType)+' · '+(d.status||'PROVISIONAL');byId('teachEvidence').textContent=d.evidenceRequired||'LUMEN va a contrastar esta enseñanza con evidencia antes de incorporarla.';input.value='';}catch(e){byId('teachStatus').className='teacher-status contradicted';byId('teachStatus').textContent='No pude registrar la enseñanza: '+String(e.message||e)}finally{btn.disabled=false}}async function critic(){const btn=byId('criticRun');btn.disabled=true;byId('criticVerdict').textContent='Revisando la decisión actual…';try{const d=await tfetch('/api/lumen-self-critic-run',{method:'POST',headers:{'content-type':'application/json'},body:'{}'},14000);byId('criticVerdict').textContent=(d.verdict||'REVIEWED')+' · '+(d.severity||'INFO');const r=d.recommendation||{};byId('criticReason').textContent=(r.reason||'Revisión completada.')+(r.whatWouldChangeMyMind?' Qué me haría cambiar de opinión: '+r.whatWouldChangeMyMind:'');}catch(e){byId('criticVerdict').textContent='No pude completar la autocrítica';byId('criticReason').textContent=String(e.message||e)}finally{btn.disabled=false}}byId('teachSend')?.addEventListener('click',teach);byId('criticRun')?.addEventListener('click',critic);loadCritic();})();
</script>`;

function injectTeachingMode(html) {
  if (html.includes('id="teacher-panel"')) return html;
  if (!html.includes('<section class="chat">')) return html;
  html = html.replace('</head>', `${TEACHING_CSS}</head>`);
  html = html.replace('<section class="chat">', `${TEACHING_HTML}<section class="chat">`);
  html = html.replace('</body>', `${TEACHING_SCRIPT}</body>`);
  return html;
}

async function proxyTeacher(request, env, targetPath) {
  const token = String(env.OPPORTUNITY_ADMIN_TOKEN || "");
  if (!token) return Response.json({ ok:false, error:"dashboard_a2a_admin_token_missing" }, { status:503, headers:{"cache-control":"no-store"} });
  try {
    let body;
    if (request.method === "POST") {
      body = await request.text();
      if (body.length > 6000) return Response.json({ ok:false, error:"request_too_large" }, { status:413, headers:{"cache-control":"no-store"} });
    }
    const headers = new Headers({ "accept":"application/json", "x-lumen-admin":token });
    if (request.method === "POST") headers.set("content-type","application/json");
    const upstream = await env.A2A.fetch(new Request(`https://lumen.internal${targetPath}`, { method:request.method, headers, body, signal:AbortSignal.timeout(12000) }));
    const text = await upstream.text();
    return new Response(text, { status:upstream.status, headers:{ "content-type":upstream.headers.get("content-type") || "application/json; charset=utf-8", "cache-control":"no-store", "x-lumen-teaching-proxy":"v1" } });
  } catch (error) {
    const timeout = String(error?.name || "").includes("Timeout") || String(error?.message || "").toLowerCase().includes("timeout");
    return Response.json({ ok:false, error:timeout?"teacher_upstream_timeout":"teacher_upstream_unavailable", detail:String(error?.message || error).slice(0,160) }, { status:timeout?504:502, headers:{"cache-control":"no-store"} });
  }
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const response = await app.fetch(request.clone(), env, ctx);
    const authenticated = response.status !== 401 && response.status !== 503;
    if (!authenticated) return response;

    if (request.method === "POST" && url.pathname === "/api/lumen-teacher-feedback") return proxyTeacher(request, env, "/teacher/feedback");
    if (request.method === "GET" && url.pathname === "/api/lumen-teacher-status") return proxyTeacher(request, env, "/teacher/status");
    if (request.method === "GET" && url.pathname === "/api/lumen-self-critic") return proxyTeacher(request, env, "/self-critic/status");
    if (request.method === "POST" && url.pathname === "/api/lumen-self-critic-run") return proxyTeacher(request, env, "/self-critic/run");

    const isConversationHtml = request.method === "GET" && url.pathname === "/conversar" && response.ok && String(response.headers.get("content-type") || "").includes("text/html");
    if (!isConversationHtml) return response;

    const html = injectTeachingMode(await response.text());
    const headers = new Headers(response.headers);
    headers.delete("content-length");
    headers.set("cache-control", "no-store, no-cache, must-revalidate");
    headers.set("x-lumen-teaching-mode", "v1");
    return new Response(html, { status:response.status, statusText:response.statusText, headers });
  }
};
