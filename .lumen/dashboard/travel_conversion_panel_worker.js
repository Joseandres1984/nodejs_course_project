import app from "./travel_revenue_panel_worker.js";

function n(v) { return Number(v || 0); }

async function safeRows(env, sql, binds = []) {
  try {
    let q = env.DB.prepare(sql);
    if (binds.length) q = q.bind(...binds);
    const result = await q.all();
    return result.results || [];
  } catch {
    return [];
  }
}

async function safeFirst(env, sql, binds = []) {
  try {
    let q = env.DB.prepare(sql);
    if (binds.length) q = q.bind(...binds);
    return await q.first();
  } catch {
    return null;
  }
}

async function conversionSnapshot(env) {
  const [state, totals, campaignBookings, campaignClicks, variantBookings, variantClicks, recent] = await Promise.all([
    safeFirst(env, "SELECT cursor,last_sync_at,last_success_at,last_error,events_seen,events_inserted,pages_seen,updated_at FROM lumen_viator_booking_sync_state WHERE id='primary'"),
    safeRows(env, "SELECT event_type,COUNT(*) total,SUM(CASE WHEN datetime(last_updated)>=datetime('now','-7 days') THEN 1 ELSE 0 END) last_7d,SUM(CASE WHEN event_type='CONFIRMATION' THEN total_price ELSE 0 END) value FROM lumen_viator_booking_events GROUP BY event_type"),
    safeRows(env, "SELECT COALESCE(NULLIF(campaign_value,''),'unattributed') campaign,SUM(CASE WHEN event_type='CONFIRMATION' THEN 1 ELSE 0 END) confirmations,SUM(CASE WHEN event_type IN ('CANCELLATION','CUSTOMER_CANCELLATION','REJECTION') THEN 1 ELSE 0 END) negative_events,SUM(CASE WHEN event_type='CONFIRMATION' THEN total_price ELSE 0 END) confirmed_value,MAX(currency) currency,MAX(last_updated) last_event FROM lumen_viator_booking_events GROUP BY COALESCE(NULLIF(campaign_value,''),'unattributed') ORDER BY confirmations DESC,confirmed_value DESC LIMIT 20"),
    safeRows(env, "SELECT COALESCE(NULLIF(campaign,''),'unattributed') campaign,COUNT(*) clicks FROM lumen_travel_events WHERE event_type='click' GROUP BY COALESCE(NULLIF(campaign,''),'unattributed')"),
    safeRows(env, "SELECT CASE WHEN campaign_value LIKE '%price_availability_v1%' THEN 'price_availability_v1' WHEN campaign_value LIKE '%dates_available_v1%' THEN 'dates_available_v1' ELSE 'other' END variant,SUM(CASE WHEN event_type='CONFIRMATION' THEN 1 ELSE 0 END) confirmations,SUM(CASE WHEN event_type IN ('CANCELLATION','CUSTOMER_CANCELLATION','REJECTION') THEN 1 ELSE 0 END) negative_events,SUM(CASE WHEN event_type='CONFIRMATION' THEN total_price ELSE 0 END) confirmed_value FROM lumen_viator_booking_events GROUP BY variant"),
    safeRows(env, "SELECT COALESCE(NULLIF(variant,''),'other') variant,COUNT(*) clicks FROM lumen_travel_events WHERE event_type='click' GROUP BY COALESCE(NULLIF(variant,''),'other')"),
    safeRows(env, "SELECT event_type,transaction_ref,product_code,campaign_value,travel_date,last_updated,total_price,currency FROM lumen_viator_booking_events ORDER BY datetime(last_updated) DESC LIMIT 15")
  ]);

  const byType = Object.fromEntries(totals.map(row => [String(row.event_type || ""), { total: n(row.total), last7d: n(row.last_7d), value: n(row.value) }]));
  const confirmations7d = n(byType.CONFIRMATION?.last7d);
  const negatives7d = n(byType.CANCELLATION?.last7d) + n(byType.CUSTOMER_CANCELLATION?.last7d) + n(byType.REJECTION?.last7d);
  const clicks7dRows = await safeRows(env, "SELECT COUNT(*) clicks FROM lumen_travel_events WHERE event_type='click' AND datetime(created_at)>=datetime('now','-7 days')");
  const clicks7d = n(clicks7dRows[0]?.clicks);
  const conversionRate7d = clicks7d > 0 ? Number(((confirmations7d / clicks7d) * 100).toFixed(2)) : null;

  const clickByCampaign = new Map(campaignClicks.map(row => [String(row.campaign), n(row.clicks)]));
  const campaigns = campaignBookings.map(row => {
    const clicks = clickByCampaign.get(String(row.campaign)) || 0;
    const confirmations = n(row.confirmations);
    return {
      campaign: String(row.campaign),
      confirmations,
      negativeEvents: n(row.negative_events),
      confirmedValue: n(row.confirmed_value),
      currency: String(row.currency || "—"),
      clicks,
      cvr: clicks > 0 ? Number(((confirmations / clicks) * 100).toFixed(2)) : null,
      lastEvent: row.last_event || null
    };
  });

  const clickByVariant = new Map(variantClicks.map(row => [String(row.variant), n(row.clicks)]));
  const variants = variantBookings.map(row => {
    const clicks = clickByVariant.get(String(row.variant)) || 0;
    const confirmations = n(row.confirmations);
    return {
      variant: String(row.variant),
      confirmations,
      negativeEvents: n(row.negative_events),
      confirmedValue: n(row.confirmed_value),
      clicks,
      cvr: clicks > 0 ? Number(((confirmations / clicks) * 100).toFixed(2)) : null
    };
  }).sort((a, b) => b.confirmations - a.confirmations || (b.cvr || 0) - (a.cvr || 0));

  const winner = variants.find(row => row.confirmations >= 3 && row.clicks >= 20) || null;

  return {
    mode: "viator_booking_api_conversion_attribution",
    sync: {
      lastSyncAt: state?.last_sync_at || null,
      lastSuccessAt: state?.last_success_at || null,
      lastError: state?.last_error || null,
      eventsSeen: n(state?.events_seen),
      eventsInserted: n(state?.events_inserted),
      pagesSeen: n(state?.pages_seen),
      cursorStored: Boolean(state?.cursor)
    },
    funnel: {
      clicks7d,
      confirmations7d,
      negativeEvents7d: negatives7d,
      conversionRate7d
    },
    campaigns,
    variants,
    winner,
    recent,
    policy: {
      minimumConfirmations: 3,
      minimumClicks: 20,
      explorationSharePct: winner ? 20 : 50,
      noFabricatedSignificance: true,
      commissionNotInferredFromBookings: true
    }
  };
}

const CONVERSION_SECTION = `<div class="grid g4 section"><div class="card"><div class="klabel">Reservas API 7 días</div><div class="kpi good" id="travelApiBookings7">–</div></div><div class="card"><div class="klabel">Conversión clic → reserva</div><div class="kpi blue" id="travelApiCvr7">–</div></div><div class="card"><div class="klabel">Cancel./rechazos 7 días</div><div class="kpi" id="travelApiNegative7">–</div></div><div class="card"><div class="klabel">Sync Viator</div><div class="kpi" id="travelApiSync">–</div></div></div><div class="grid g2 section"><div class="card"><h2>Conversión por campaña</h2><div id="travelConversionCampaigns"></div></div><div class="card"><h2>Optimización CTA</h2><div id="travelConversionVariants"></div></div></div>`;

const CONVERSION_RENDER_JS = `function renderTravelConversion(t){
  const c=t?.conversion||{};
  const f=c.funnel||{};
  const s=c.sync||{};
  $('travelApiBookings7').textContent=num(f.confirmations7d||0).toLocaleString('es-AR');
  $('travelApiCvr7').textContent=f.conversionRate7d==null?'—':num(f.conversionRate7d).toLocaleString('es-AR',{maximumFractionDigits:2})+'%';
  $('travelApiNegative7').textContent=num(f.negativeEvents7d||0).toLocaleString('es-AR');
  $('travelApiSync').textContent=s.lastSuccessAt?'OK':'PEND.';
  $('travelConversionCampaigns').innerHTML=table([['Campaña',x=>esc(x.campaign)],['Clics',x=>num(x.clicks)],['Reservas',x=>num(x.confirmations)],['CVR',x=>x.cvr==null?'—':num(x.cvr).toFixed(2)+'%'],['Valor',x=>esc(x.currency||'')+' '+num(x.confirmedValue).toLocaleString('es-AR',{maximumFractionDigits:2})]],c.campaigns||[]);
  const winner=c.winner;
  const winnerNote=winner?'<p class="note"><strong>Ganador con evidencia:</strong> '+esc(winner.variant)+' · exploración '+num(c.policy?.explorationSharePct||20)+'%.</p>':'<p class="note">Todavía no hay muestra suficiente para declarar un CTA ganador. LUMEN mantiene exploración 50/50 hasta reunir evidencia mínima.</p>';
  $('travelConversionVariants').innerHTML=table([['CTA',x=>esc(x.variant)],['Clics',x=>num(x.clicks)],['Reservas',x=>num(x.confirmations)],['CVR',x=>x.cvr==null?'—':num(x.cvr).toFixed(2)+'%'],['Negativos',x=>num(x.negativeEvents)]],c.variants||[])+winnerNote+'<p class="note">Una reserva confirmada no se registra como comisión cobrada. El efectivo sigue dependiendo del payout verificado de Viator.</p>';
}`;

function injectConversionUI(html) {
  if (!html.includes('id="travelApiBookings7"')) {
    const marker = '<div class="grid g2 section"><div class="card"><h2>Comisiones Viator</h2>';
    if (html.includes(marker)) html = html.replace(marker, `${CONVERSION_SECTION}${marker}`);
  }
  if (!html.includes('function renderTravelConversion(t)')) {
    const marker = 'function renderTravelRevenue(t){';
    if (html.includes(marker)) html = html.replace(marker, `${CONVERSION_RENDER_JS}\nfunction renderTravelRevenue(t){\n  renderTravelConversion(t);`);
  }
  return html;
}

function injectConversationLink(html) {
  if (html.includes('href="/conversar"')) return html;
  const link = `<a href="/conversar" style="position:fixed;right:18px;bottom:18px;z-index:9999;text-decoration:none;background:#d9ff65;color:#061019;border:1px solid #e8ff9d;border-radius:999px;padding:12px 16px;font:900 13px Inter,system-ui,-apple-system,Segoe UI,Arial,sans-serif;box-shadow:0 12px 30px #0008">Hablar con LUMEN</a>`;
  return html.includes("</body>") ? html.replace("</body>", `${link}</body>`) : `${html}${link}`;
}

function conversationPage() {
  return `<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#061019"><title>LUMEN · Conversación operativa</title><style>
  :root{color-scheme:dark;--bg:#061019;--panel:#0d1b24;--line:#21404e;--text:#edf5f7;--muted:#8da6b2;--lime:#d9ff65;--good:#9de8c5;--bad:#ff9992;--blue:#83d9ff}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 100% 0,#12303d 0,#061019 38%) fixed;color:var(--text);font:14px Inter,system-ui,-apple-system,Segoe UI,Arial,sans-serif}.wrap{max-width:980px;margin:auto;padding:20px}.top{display:flex;justify-content:space-between;align-items:center;gap:15px;margin-bottom:16px}.brand{font-size:28px;font-weight:950;letter-spacing:.1em}.sub{color:var(--muted);margin-top:4px}.back{color:#d9edf5;text-decoration:none;border:1px solid #2c5264;border-radius:10px;padding:9px 12px;font-weight:800}.mind{display:grid;grid-template-columns:repeat(4,1fr);gap:9px;margin-bottom:12px}.k{background:#0b1720;border:1px solid var(--line);border-radius:13px;padding:12px}.kl{font-size:10px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);font-weight:900}.kv{font-size:16px;font-weight:900;margin-top:6px;overflow-wrap:anywhere}.chat{background:linear-gradient(180deg,#0e1b24,#09151d);border:1px solid var(--line);border-radius:18px;overflow:hidden;box-shadow:0 18px 45px #0005}.messages{min-height:430px;max-height:62vh;overflow:auto;padding:18px}.msg{display:flex;margin:0 0 12px}.bubble{max-width:82%;padding:12px 14px;border-radius:15px;line-height:1.55;white-space:pre-wrap}.user{justify-content:flex-end}.user .bubble{background:#193342;border:1px solid #2d566a}.assistant .bubble{background:#132018;border:1px solid #38552a}.meta{font-size:10px;color:var(--muted);margin-top:5px}.quick{display:flex;gap:7px;flex-wrap:wrap;padding:0 16px 12px}.quick button{background:#0d202a;color:#cfe6ef;border:1px solid #294b5b;border-radius:999px;padding:8px 10px;cursor:pointer;font-weight:750}.composer{display:grid;grid-template-columns:1fr auto;gap:8px;border-top:1px solid var(--line);padding:14px;background:#08141b}.composer textarea{resize:vertical;min-height:50px;max-height:150px;background:#061019;color:var(--text);border:1px solid #294857;border-radius:12px;padding:12px;font:inherit}.send{border:0;border-radius:12px;background:var(--lime);color:#061019;font-weight:950;padding:0 18px;cursor:pointer}.send:disabled{opacity:.5;cursor:wait}.truth{color:var(--muted);font-size:12px;line-height:1.5;margin:12px 2px 0}.status-good{color:var(--good)}.status-bad{color:var(--bad)}@media(max-width:700px){.mind{grid-template-columns:1fr 1fr}.wrap{padding:12px}.top{align-items:flex-start}.bubble{max-width:94%}.composer{grid-template-columns:1fr}.send{padding:12px}.messages{min-height:360px}}
  </style></head><body><main class="wrap"><header class="top"><div><div class="brand">LUMEN</div><div class="sub">Conversación operativa · Superautonomía + estado real</div></div><a class="back" href="/">← Centro de Comando</a></header><section class="mind"><div class="k"><div class="kl">Fase</div><div class="kv" id="phase">—</div></div><div class="k"><div class="kl">Cuello de botella</div><div class="kv" id="bottleneck">—</div></div><div class="k"><div class="kl">Próxima acción</div><div class="kv" id="next">—</div></div><div class="k"><div class="kl">Autonomía acotada</div><div class="kv" id="ratio">—</div></div></section><section class="chat"><div class="messages" id="messages"></div><div class="quick"><button data-q="¿Qué estás haciendo ahora y por qué?">¿Qué estás haciendo?</button><button data-q="¿Qué aprendiste últimamente y qué cambió por eso?">¿Qué aprendiste?</button><button data-q="¿Cómo pensás mejorar a partir de ahora?">¿Cómo vas a mejorar?</button><button data-q="¿Qué necesitás de mí y qué podés resolver solo?">¿Qué necesitás de mí?</button><button data-q="¿Qué pasa con Gmail y cómo afecta tu autonomía?">¿Qué pasa con Gmail?</button></div><form class="composer" id="form"><textarea id="input" maxlength="1800" placeholder="Preguntale a LUMEN qué está haciendo, qué aprendió o qué piensa probar después…"></textarea><button class="send" id="send" type="submit">Enviar</button></form></section><p class="truth">LUMEN responde desde datos operativos registrados y memoria de Superautonomía. Puede resumir razones, evidencia y próximos pasos, pero no expone cadena de pensamiento privada ni afirma conciencia. Los pagos, contratos y otras acciones vinculantes siguen bajo aprobación humana.</p></main><script>
  const $=id=>document.getElementById(id), box=$('messages'), form=$('form'), input=$('input'), send=$('send');
  function add(role,text,meta=''){const row=document.createElement('div');row.className='msg '+role;const b=document.createElement('div');b.className='bubble';b.textContent=text;row.appendChild(b);if(meta){const m=document.createElement('div');m.className='meta';m.textContent=meta;b.appendChild(document.createElement('br'));b.appendChild(m)}box.appendChild(row);box.scrollTop=box.scrollHeight;}
  function setMind(s){const x=s?.snapshot?.superautonomy||s?.superautonomy||{};$('phase').textContent=x.phase||'—';$('bottleneck').textContent=x.bottleneck||'—';$('next').textContent=x.nextAction||x.next_action||'—';const r=Number(x.boundedAutonomyRatio??x.autonomy_ratio);$('ratio').textContent=Number.isFinite(r)?Math.round(r*100)+'%':'—';}
  async function load(){try{const [mind,hist]=await Promise.all([fetch('/api/lumen-mind',{cache:'no-store'}),fetch('/api/lumen-conversation',{cache:'no-store'})]);if(mind.ok){const d=await mind.json();setMind(d.snapshot||d);if(!hist.ok&&d.summary)add('assistant',d.summary,'estado actual')}if(hist.ok){const h=await hist.json();for(const t of h.history||[])add(t.role==='user'?'user':'assistant',t.message,t.role==='assistant'?'memoria persistente':'')}}catch(e){add('assistant','No pude leer mi estado conversacional en este momento. El resto de LUMEN puede seguir operando; revisá el estado del sistema.','fallback local')}}
  async function ask(text){text=String(text||'').trim();if(!text)return;add('user',text);input.value='';send.disabled=true;try{const r=await fetch('/api/lumen-talk',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({message:text})});const d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||('HTTP '+r.status));add('assistant',d.reply,d.provider==='cloudflare_workers_ai_grounded'?'Workers AI · grounded':'fallback determinístico · grounded');setMind(d.snapshot||{});}catch(e){add('assistant','No pude responder con estado verificado ahora: '+String(e.message||e),'error');}finally{send.disabled=false;input.focus()}}
  form.addEventListener('submit',e=>{e.preventDefault();ask(input.value)});document.querySelectorAll('[data-q]').forEach(b=>b.addEventListener('click',()=>ask(b.dataset.q)));input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();form.requestSubmit()}});load();
</script></body></html>`;
}

async function proxyConversation(request, env, targetPath) {
  const token = String(env.OPPORTUNITY_ADMIN_TOKEN || "");
  if (!token) return Response.json({ ok:false, error:"dashboard_a2a_admin_token_missing" }, { status:503, headers:{"cache-control":"no-store"} });
  try {
    let body;
    if (request.method === "POST") {
      body = await request.text();
      if (body.length > 6000) return Response.json({ ok:false, error:"request_too_large" }, { status:413 });
    }
    const headers = new Headers({ "accept":"application/json", "x-lumen-admin":token });
    if (request.method === "POST") headers.set("content-type","application/json");
    const upstream = await env.A2A.fetch(new Request(`https://lumen.internal${targetPath}`, { method:request.method, headers, body }));
    const text = await upstream.text();
    const outHeaders = new Headers({ "content-type":upstream.headers.get("content-type") || "application/json; charset=utf-8", "cache-control":"no-store", "x-lumen-conversation-proxy":"v1" });
    return new Response(text, { status:upstream.status, headers:outHeaders });
  } catch (error) {
    return Response.json({ ok:false, error:"conversation_upstream_unavailable", detail:String(error?.message || error).slice(0,160) }, { status:502, headers:{"cache-control":"no-store"} });
  }
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const baseRequest = request.clone();
    const response = await app.fetch(baseRequest, env, ctx);

    const authenticated = response.status !== 401 && response.status !== 503;
    if (url.pathname === "/conversar" && request.method === "GET") {
      if (!authenticated) return response;
      return new Response(conversationPage(), { headers:{ "content-type":"text/html; charset=utf-8", "cache-control":"no-store", "x-frame-options":"DENY", "referrer-policy":"no-referrer", "x-content-type-options":"nosniff", "content-security-policy":"default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'" } });
    }
    if (authenticated && request.method === "POST" && url.pathname === "/api/lumen-talk") return proxyConversation(request, env, "/lumen/talk");
    if (authenticated && request.method === "GET" && url.pathname === "/api/lumen-mind") return proxyConversation(request, env, "/lumen/mind");
    if (authenticated && request.method === "GET" && url.pathname === "/api/lumen-conversation") return proxyConversation(request, env, "/lumen/conversation");

    if (request.method === "GET" && url.pathname === "/api/data" && response.ok && String(response.headers.get("content-type") || "").includes("application/json")) {
      try {
        const data = await response.json();
        data.travel = data.travel || {};
        data.travel.conversion = await conversionSnapshot(env);
        const headers = new Headers(response.headers);
        headers.delete("content-length");
        headers.set("cache-control", "no-store");
        headers.set("x-lumen-travel-conversion", "v2");
        return Response.json(data, { status: response.status, headers });
      } catch {
        return response;
      }
    }

    const isHtml = request.method === "GET"
      && response.ok
      && ["/", "/index.html", "/full", "/secretaria", "/secretaria/"].includes(url.pathname)
      && String(response.headers.get("content-type") || "").includes("text/html");
    if (!isHtml) return response;

    let html = await response.text();
    html = injectConversionUI(html);
    html = injectConversationLink(html);
    const headers = new Headers(response.headers);
    headers.delete("content-length");
    headers.set("cache-control", "no-store, no-cache, must-revalidate");
    headers.set("x-lumen-travel-conversion-panel", "v2");
    headers.set("x-lumen-conversational-mind", "v1");
    return new Response(html, { status: response.status, statusText: response.statusText, headers });
  }
};
