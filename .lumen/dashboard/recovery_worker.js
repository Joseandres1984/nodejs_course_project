import base from "./full_worker.js";

const STATE_KEY = "global";
const RECOVERY_KEY = "railway_20260919";

function constantTimeEqual(a,b){a=String(a||"");b=String(b||"");if(a.length!==b.length)return false;let d=0;for(let i=0;i<a.length;i++)d|=a.charCodeAt(i)^b.charCodeAt(i);return d===0;}
function authOK(request,env){const p=String(env.LUMEN_DASHBOARD_PASSWORD||"");if(!p)return null;const h=request.headers.get("Authorization")||"";if(!h.startsWith("Basic "))return false;try{const x=atob(h.slice(6));const i=x.indexOf(":");if(i<0)return false;return constantTimeEqual(x.slice(0,i),String(env.LUMEN_DASHBOARD_USER||"socio"))&&constantTimeEqual(x.slice(i+1),p);}catch{return false;}}
function unauthorized(){return new Response("LUMEN · acceso restringido",{status:401,headers:{"WWW-Authenticate":'Basic realm="LUMEN Centro de Comando", charset="UTF-8"',"Cache-Control":"no-store"}});}
function locked(){return new Response("LUMEN dashboard todavía no tiene contraseña configurada.",{status:503,headers:{"Cache-Control":"no-store"}});}
async function sha256Hex(bytes){const hash=await crypto.subtle.digest("SHA-256",bytes);return [...new Uint8Array(hash)].map(b=>b.toString(16).padStart(2,"0")).join("");}
async function loadState(env){const m=await env.DB.prepare("SELECT encoding,chunk_count,payload_sha256,uncompressed_bytes,updated_at FROM lumen_state_manifest WHERE state_key=? LIMIT 1").bind(STATE_KEY).first();if(!m)throw new Error("state_not_initialized");const r=await env.DB.prepare("SELECT chunk_no,payload FROM lumen_state_chunks WHERE state_key=? ORDER BY chunk_no ASC").bind(STATE_KEY).all();const chunks=r.results||[];if(chunks.length!==Number(m.chunk_count||0))throw new Error("incomplete_state_chunks");const enc=chunks.map(x=>String(x.payload||"")).join("");const bin=atob(enc);const compressed=new Uint8Array(bin.length);for(let i=0;i<bin.length;i++)compressed[i]=bin.charCodeAt(i);const stream=new Blob([compressed]).stream().pipeThrough(new DecompressionStream("deflate"));const raw=new Uint8Array(await new Response(stream).arrayBuffer());if(m.payload_sha256&&await sha256Hex(raw)!==m.payload_sha256)throw new Error("state_checksum_mismatch");return {state:JSON.parse(new TextDecoder().decode(raw)),manifest:m};}
const arr=v=>Array.isArray(v)?v:[];const obj=v=>v&&typeof v==="object"&&!Array.isArray(v)?v:{};const n=v=>Number(v||0);const s=v=>String(v??"");

function recoverySummary(state,manifest){
  const root=obj(state.legacy_recovery);const recovery=obj(root[RECOVERY_KEY]);const queue=arr(recovery.reverification_queue);const accounts=arr(recovery.accounts);const runtime=obj(recovery.fresh_reverification_runtime);const candidates=arr(state.candidate_accounts).filter(x=>x&&x.legacy_reverification===true);
  const counts={};for(const row of queue){const k=s(row&&row.status)||"unknown";counts[k]=(counts[k]||0)+1;}
  const verified=candidates.filter(x=>x&&x.verified_company===true);const contacts=verified.filter(x=>x&&x.verified_contact===true&&s(x.commercial_email));
  const attempted=queue.filter(x=>n(x&&x.fresh_reverification_attempts)>0||s(x&&x.current_candidate_id)).length;
  const pending=(counts.pending_reverification||0)+(counts.retry_required||0)+(counts.fresh_classification_retry||0)+(counts.current_verification_retry||0);
  const rows=queue.slice().sort((a,b)=>{
    const rank=x=>s(x.status).includes("verified")?0:s(x.current_candidate_id)?1:s(x.status)==="pending_reverification"?2:3;
    return rank(a)-rank(b)||n(b.priority)-n(a.priority)||s(a.official_domain).localeCompare(s(b.official_domain));
  }).slice(0,60).map(x=>({domain:s(x.official_domain),status:s(x.status),priority:n(x.priority),type:s(x.fresh_type||x.type),candidate_id:s(x.current_candidate_id),attempts:n(x.fresh_reverification_attempts),fresh_company_verified:Boolean(x.status==="fresh_company_verified"),fresh_contact_verified:Boolean(x.fresh_contact_verified),do_not_contact:Boolean(x.do_not_contact),eligible_after:s(x.eligible_after)}));
  return {
    available:Boolean(recovery&&Object.keys(recovery).length),
    snapshot_at:s(recovery.snapshot_at),imported_at:s(recovery.imported_at),state_updated_at:s(manifest.updated_at),archive_sha256:s(recovery.archive_sha256),
    policy:{historical_only:Boolean(recovery.historical_only),requires_reverification_before_outbound:Boolean(recovery.requires_reverification_before_outbound),auto_promoted:n(recovery.auto_promoted_to_current_pipeline),safe_for_outbound:n(recovery.safe_for_outbound_count),preserve_opt_outs:Boolean(obj(recovery.policy).preserve_opt_outs)},
    historical:{accounts:accounts.length||n(obj(recovery.legacy_summary).commercial_accounts),unique_domains:queue.length,eligible_at_snapshot:n(obj(recovery.legacy_summary).eligible_at_legacy_snapshot),summary:obj(recovery.legacy_summary)},
    progress:{attempted_domains:attempted,pending,queued_current_verification:counts.queued_current_verification||0,fresh_company_verified:verified.length,fresh_contact_verified:contacts.length,cooldown:counts.legacy_contact_cooldown||0,suppressed:counts.suppressed_do_not_contact||0,insufficient:counts.fresh_evidence_insufficient||0,retry:(counts.fresh_classification_retry||0)+(counts.current_verification_retry||0),total_domains:queue.length},
    runtime:{status:s(runtime.status),attempted:n(runtime.attempted),classified:n(runtime.classified),created:n(runtime.created),linked_verified:n(runtime.linked_verified),linked_contact_verified:n(runtime.linked_contact_verified),updated_at:s(runtime.updated_at),max_per_cycle:n(runtime.max_per_cycle)},
    current_recovered:candidates.slice(0,60).map(x=>({id:s(x.id),domain:s(x.domain),type:s(x.type),category:s(x.category),verification_status:s(x.verification_status),verification_score:n(x.verification_score),verified_company:Boolean(x.verified_company),verified_contact:Boolean(x.verified_contact),outbound_suppressed:Boolean(x.outbound_suppressed),next_action:s(x.next_action)})),
    queue_preview:rows,
    truth_rule:"Histórico Railway ≠ verdad actual. Cada dominio debe volver a superar evidencia corporativa, verificación de empresa y verificación de contacto antes de cualquier outbound."
  };
}
function json(data,status=200){return new Response(JSON.stringify(data),{status,headers:{"Content-Type":"application/json; charset=utf-8","Cache-Control":"no-store","X-Content-Type-Options":"nosniff"}});}

const RECOVERY_SECTION=`<section class="page" id="recovery"><div class="grid g6"><div class="card"><div class="lab">Cuentas históricas</div><div class="kpi" id="lrAccounts">–</div></div><div class="card"><div class="lab">Dominios únicos</div><div class="kpi" id="lrDomains">–</div></div><div class="card"><div class="lab">Revisados fresco</div><div class="kpi blue" id="lrAttempted">–</div></div><div class="card"><div class="lab">Empresas re-verificadas</div><div class="kpi good" id="lrVerified">–</div></div><div class="card"><div class="lab">Contactos re-verificados</div><div class="kpi good" id="lrContacts">–</div></div><div class="card"><div class="lab">Pendientes</div><div class="kpi warn" id="lrPending">–</div></div></div><div class="grid g2 section"><div class="card"><h2>Restauración Railway → D1</h2><div id="lrStatus"></div></div><div class="card"><h2>Seguridad de recuperación</h2><div id="lrPolicy"></div></div></div><div class="grid g2 section"><div class="card"><h2>Cuentas recuperadas al estado vivo</h2><div id="lrCurrent"></div></div><div class="card"><h2>Cola histórica priorizada</h2><div id="lrQueue"></div></div></div><div class="card section"><h2>Regla de verdad</h2><div class="notice" id="lrTruth"></div></div></section>`;

const RECOVERY_SCRIPT=`
let LR=null;
function lrLine(a,b){return '<div class="module"><strong>'+esc(a)+'</strong><div class="muted">'+b+'</div></div>';}
function lrBool(v){return v?'<span class="chip">SÍ</span>':'<span class="chip">NO</span>';}
function lrTable(rows){if(!Array.isArray(rows)||!rows.length)return '<div class="empty">Sin registros.</div>';const cols=['domain','status','type','verification_score','verified_company','verified_contact','next_action'];const labels={domain:'Dominio',status:'Estado',type:'Tipo',verification_score:'Score',verified_company:'Empresa verificada',verified_contact:'Contacto verificado',next_action:'Próxima acción'};return '<div style="overflow:auto"><table><thead><tr>'+cols.map(c=>'<th>'+labels[c]+'</th>').join('')+'</tr></thead><tbody>'+rows.slice(0,40).map(r=>'<tr>'+cols.map(c=>'<td>'+esc(typeof r[c]==='boolean'?(r[c]?'sí':'no'):(r[c]??'—'))+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>';}
function lrQueueTable(rows){if(!Array.isArray(rows)||!rows.length)return '<div class="empty">Sin cola histórica.</div>';return '<div style="overflow:auto"><table><thead><tr><th>Dominio</th><th>Estado</th><th>Prioridad</th><th>Tipo</th><th>Intentos</th></tr></thead><tbody>'+rows.slice(0,50).map(r=>'<tr><td class="mono">'+esc(r.domain)+'</td><td>'+esc(r.status)+'</td><td>'+esc(r.priority)+'</td><td>'+esc(r.type||'—')+'</td><td>'+esc(r.attempts)+'</td></tr>').join('')+'</tbody></table></div>';}
function renderRecovery(){if(!LR||!LR.available){document.getElementById('lrStatus').innerHTML='<div class="empty">El archivo histórico todavía no está disponible.</div>';return;}const p=LR.progress,h=LR.historical,rt=LR.runtime,pol=LR.policy;document.getElementById('lrAccounts').textContent=h.accounts;document.getElementById('lrDomains').textContent=h.unique_domains;document.getElementById('lrAttempted').textContent=p.attempted_domains;document.getElementById('lrVerified').textContent=p.fresh_company_verified;document.getElementById('lrContacts').textContent=p.fresh_contact_verified;document.getElementById('lrPending').textContent=p.pending;document.getElementById('lrStatus').innerHTML=lrLine('Snapshot Railway',esc(LR.snapshot_at||'—'))+lrLine('Importado a D1',esc(LR.imported_at||'—'))+lrLine('Runtime',esc(rt.status||'—')+' · máximo '+esc(rt.max_per_cycle)+' dominios por ciclo')+lrLine('Último ciclo de recuperación',esc(rt.updated_at||'—'))+lrLine('Cooldown histórico',esc(p.cooldown))+lrLine('Do-not-contact preservados',esc(p.suppressed));document.getElementById('lrPolicy').innerHTML=lrLine('Histórico solamente',lrBool(pol.historical_only))+lrLine('Re-verificación obligatoria',lrBool(pol.requires_reverification_before_outbound))+lrLine('Auto-promovidos',esc(pol.auto_promoted))+lrLine('Marcados outbound-safe por el importador',esc(pol.safe_for_outbound))+lrLine('Opt-outs preservados',lrBool(pol.preserve_opt_outs));document.getElementById('lrCurrent').innerHTML=lrTable(LR.current_recovered);document.getElementById('lrQueue').innerHTML=lrQueueTable(LR.queue_preview);document.getElementById('lrTruth').textContent=LR.truth_rule;}
async function loadRecovery(){try{const r=await fetch('/api/recovery-state',{cache:'no-store'});if(!r.ok)return;LR=await r.json();renderRecovery();}catch(e){console.error('recovery panel',e);}}
loadRecovery();setInterval(loadRecovery,60000);
`;

function patchFullHtml(html){
  if(html.includes('data-p="recovery"'))return html;
  let out=html.replace('<button class="tab" data-p="state">Estado vivo</button>','<button class="tab" data-p="recovery">Recuperación Railway</button><button class="tab" data-p="state">Estado vivo</button>');
  out=out.replace('<section class="page" id="state">',RECOVERY_SECTION+'<section class="page" id="state">');
  out=out.replace('</script></body></html>',RECOVERY_SCRIPT+'</script></body></html>');
  out=out.replace('onclick="load()"','onclick="load();loadRecovery()"');
  return out;
}

export default {async fetch(request,env,ctx){
  const url=new URL(request.url);
  if(request.method==="GET"&&url.pathname==="/api/recovery-state"){
    const auth=authOK(request,env);if(auth===null)return locked();if(!auth)return unauthorized();
    try{const {state,manifest}=await loadState(env);return json(recoverySummary(state,manifest));}catch(e){return json({ok:false,error:String(e&&e.message||e)},503);}
  }
  const response=await base.fetch(request,env,ctx);
  if(request.method==="GET"&&url.pathname==="/full"&&response.ok&&response.headers.get("content-type")?.includes("text/html")){
    const html=patchFullHtml(await response.text());const headers=new Headers(response.headers);headers.set("Cache-Control","no-store");return new Response(html,{status:response.status,headers});
  }
  return response;
}};
