/* AURA 1.3: respuesta fiable antes que respuestas inventadas. */
(() => {
'use strict';
const MODE_KEY='aura.brain.mode.v13',CODE_KEY='aura.private.code.v13';
let mode='local',code='',authorized=false,explicitMode=false,loginDialog=null;
try{
  const saved=localStorage.getItem(MODE_KEY);
  explicitMode=!!saved;
  mode=saved||sessionStorage.getItem(MODE_KEY)||'local';
  // Migración: la autorización anterior duraba una sola pestaña.
  code=sessionStorage.getItem(CODE_KEY)||'';
}catch{}
const $=id=>document.getElementById(id);
const normalize=v=>String(v||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/\s+/g,' ').trim();
const forbidden=/\b(?:por favor responde en espanol|idioma obligatorio|tu unica tarea|please respond|translate the following|system prompt|instrucciones internas)\b/i;
const weakAnswer='No logré generar una respuesta coherente con el modelo local. No voy a inventar algo. Para consultas abiertas, necesitamos conectar el cerebro avanzado o probar otro modelo compatible con este iPhone.';
function isBad(question,answer){
  const q=normalize(question),a=normalize(answer);
  if(!a||a.length<5||a===q||forbidden.test(a))return true;
  if(window.AuraLanguage?.isMostlyEnglish?.(answer))return true;
  if(/presentat|quien sos|quien eres|que sos/.test(q)&&!/(soy|aura|asistente|ayudo|ayudarte|puedo ayudarte|me llamo)/.test(a))return true;
  if(/ideas? de negocio|negocio digital/.test(q)&&!/(negocio|servicio|digital|cliente|producto|plantilla|idea|venta|comercio|ofrecer)/.test(a))return true;
  if(/organiza|ordena|planifica/.test(q)&&/tarea|dia|hoy/.test(q)&&!/(tarea|prioridad|urgente|lista|organizar|plan|bloque)/.test(a))return true;
  if(a.length>24 && /(\b\w{3,}\b)(?:[., ]+\1){3,}/i.test(a))return true;
  return false;
}
async function getStatus(){
  try{const response=await fetch('./api/aura/status',{cache:'no-store'});if(!response.ok)throw Error('Error de estado');return await response.json();}
  catch{return {advancedConfigured:false,connectionError:true};}
}

async function login(pass){
  const response=await fetch('./api/aura/login',{method:'POST',cache:'no-store',credentials:'same-origin',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({code:pass})});
  const data=await response.json().catch(()=>({}));
  if(!response.ok)throw Error(data.error||'No se pudo abrir la sesión de AURA.');
  authorized=true;
  code='';
  try{sessionStorage.removeItem(CODE_KEY);}catch{}
  return data;
}
function showLogin(){
  if(!loginDialog){
    loginDialog=document.createElement('section');
    loginDialog.id='auraSessionDialog';
    loginDialog.setAttribute('role','dialog');
    loginDialog.setAttribute('aria-modal','true');
    loginDialog.setAttribute('aria-label','Conectar AURA');
    loginDialog.style.cssText='position:fixed;z-index:10050;inset:0;display:grid;place-items:end center;padding:18px;background:rgba(2,10,20,.80);backdrop-filter:blur(8px)';
    loginDialog.innerHTML='<form id="auraSessionForm" style="width:min(460px,100%);margin:auto auto 16px;border:1px solid #4a968f;border-radius:24px;padding:24px;background:linear-gradient(155deg,#102f3b,#091723);box-shadow:0 18px 70px #000a;color:#e9fffa">'+
      '<div style="font-size:12px;letter-spacing:.18em;color:#81f8dd;font-weight:800">AURA · ACCESO PERSONAL</div>'+
      '<h2 style="font-size:24px;margin:10px 0 8px">Conectá tu asistente una sola vez</h2>'+
      '<p style="font-size:13px;line-height:1.5;color:#b6d7d8">Tu iPhone conservará una sesión protegida durante 30 días. No guardamos el código secreto en este navegador.</p>'+
      '<label style="display:block;font-size:13px;margin-top:17px">Código privado<input id="auraSessionCode" type="password" required autocomplete="off" maxlength="120" placeholder="Ingresalo por única vez" style="display:block;margin-top:8px;width:100%;padding:14px;border-radius:12px;background:#081824;border:1px solid #53908d;color:white;font-size:16px"></label>'+
      '<p id="auraSessionError" role="status" aria-live="polite" style="min-height:20px;font-size:12px;color:#f4b9aa"></p>'+
      '<button id="auraSessionSubmit" type="submit" style="display:block;width:100%;border:0;border-radius:13px;padding:15px;background:#76f4dc;color:#06292d;font-weight:800;font-size:15px">Conectar y recordar este iPhone</button>'+
      '<button id="auraSessionLater" type="button" style="display:block;width:100%;border:0;padding:13px;background:transparent;color:#a7c7c9">Ahora no</button></form>';
    loginDialog.querySelector('#auraSessionForm').addEventListener('submit',async e=>{
      e.preventDefault();
      const btn=loginDialog.querySelector('#auraSessionSubmit');
      const error=loginDialog.querySelector('#auraSessionError');
      btn.disabled=true;error.textContent='Conectando de forma segura…';
      try{
        await login(loginDialog.querySelector('#auraSessionCode').value.trim());
        loginDialog.querySelector('#auraSessionCode').value='';
        loginDialog.hidden=true;
        const status=document.getElementById('auraBrain13Status');
        if(status)status.textContent='Sesión segura activa. AURA está conectada y lista para conversar.';
        const access=document.getElementById('auraBrain13Access');if(access)access.hidden=true;
      }catch(err){error.textContent=err.message||'No se pudo conectar AURA.';}
      finally{btn.disabled=false;}
    });
    loginDialog.querySelector('#auraSessionLater').addEventListener('click',()=>{loginDialog.hidden=true;});
    document.body.append(loginDialog);
  }
  loginDialog.hidden=false;
}
async function callCloud(state){
  const q=(state?.messages||[]).filter(m=>m.role==='user').at(-1)?.text||'';
  if(!q.trim())throw Error('Falta la consulta.');
  if(!authorized){
    const status=await getStatus();
    authorized=!!status.sessionActive;
    if(!authorized){showLogin();throw Error('Conectá AURA una sola vez para continuar hablando.');}
  }
  const messages=(state?.messages||[]).filter(x=>x&&['user','assistant'].includes(x.role)&&typeof x.text==='string'&&!forbidden.test(normalize(x.text))).slice(-10);
  const image=window.AuraVision?.payload?.() || null;
  const response=await fetch('./api/aura/chat',{method:'POST',cache:'no-store',
    credentials:'same-origin',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({messages,personality:state.personality,...(image?{image}:{})})});
  const data=await response.json().catch(()=>({}));
  if(response.status===401){authorized=false;showLogin();}
  if(!response.ok)throw Error(data.error||'No se pudo conectar la IA avanzada.');
  if(isBad(q,data.answer))throw Error('El proveedor devolvió una respuesta que no pasó el control de calidad.');
  if(image)window.AuraVision?.onSent?.();
  return data.answer;
}
async function respond(engine,state){
  if(mode==='cloud')return callCloud(state);
  if(!engine)throw Error('El cerebro local está desactivado. Entrá en el panel de IA y tocá «Activar cerebro».');
  const question=(state?.messages||[]).filter(x=>x.role==='user').at(-1)?.text||'';
  const answer=await window.AuraLanguage.respond(engine,state);
  return isBad(question,answer)?weakAnswer:answer;
}
window.AuraBrain={respond,isCloud:()=>mode==='cloud',isBad,getStatus,showLogin,isAuthorized:()=>authorized};
function render(){
  const brain=document.querySelector('.brain-box');
  if(!brain)return;
  const el=document.createElement('section');el.className='form-card';el.id='auraBrain13';
  el.style.cssText='margin:12px 0 16px;padding:15px;border:1px solid #32748b;background:linear-gradient(135deg,#102938,#111c2f);';
  el.innerHTML='<strong style="display:block;font-size:16px;margin-bottom:8px">Cerebro de AURA · 1.3</strong>'+
    '<label style="font-size:13px;color:#b5cddc;display:block;margin-bottom:8px">¿Cómo querés que responda?'+
    '<select id="auraBrain13Mode" style="width:100%;padding:11px;margin-top:7px;background:#0c2031;color:#ecffff;border:1px solid #39607a;border-radius:8px">'+
    '<option value="local">En mi iPhone — experimental, sin API</option>'+
    '<option value="cloud">Avanzado por internet — requiere conexión privada</option></select></label>'+
    '<p id="auraBrain13Status" style="font-size:12px;line-height:1.5;color:#bddbdc">Comprobando...</p>'+
    '<div id="auraBrain13Access" hidden><label style="font-size:12px;color:#c0e6eb">Código privado de AURA'+
    '<input id="auraBrain13Code" type="password" autocomplete="off" placeholder="Solo la primera vez o al vencer la sesión" style="display:block;width:100%;padding:12px;margin:8px 0;background:#071722;border:1px solid #39607a;color:white;border-radius:9px"></label>'+
    '<button id="auraBrain13Save" type="button" class="secondary">Conectar AURA durante 30 días</button>'+
    '<p style="font-size:11px;line-height:1.5;color:#9fb7c8">Al usar la nube, se envía el contexto reciente de conversación al proveedor. La modalidad gratuita puede utilizar datos para mejorar sus servicios. No compartas claves de API en este campo.</p></div>';
  brain.parentElement.insertBefore(el,brain);
  const select=$('auraBrain13Mode'),status=$('auraBrain13Status'),access=$('auraBrain13Access');
  select.value=mode;
  function draw(){
    access.hidden=mode!=='cloud';
    if(mode==='local'){status.textContent='Modo local experimental: puede equivocarse. Las respuestas incoherentes se rechazan cuando se detectan; no está garantizada su precisión.';}
    else{status.textContent='Cerebro avanzado seleccionado. Comprobando conexión privada...';}
  }
  select.addEventListener('change',()=>{
    mode=select.value;explicitMode=true;
    try{localStorage.setItem(MODE_KEY,mode);sessionStorage.setItem(MODE_KEY,mode)}catch{}
    draw();if(mode==='cloud')check();
  });
  $('auraBrain13Save').addEventListener('click',async()=>{
    const value=$('auraBrain13Code').value.trim();
    if(!value){showLogin();return;}
    try{await login(value);$('auraBrain13Code').value='';status.textContent='Sesión segura activa durante 30 días.';access.hidden=true;}
    catch(e){status.textContent=e.message||'Error de conexión';}
  });
  async function check(){
    const data=await getStatus();
    if(!explicitMode&&data.advancedConfigured){
      mode='cloud';select.value=mode;
      try{localStorage.setItem(MODE_KEY,mode)}catch{}
    }
    authorized=!!data.sessionActive;
    if(!authorized&&code&&data.advancedConfigured){
      try{await login(code);}
      catch(e){console.warn('No se pudo migrar la sesión anterior.');}
      finally{code='';try{sessionStorage.removeItem(CODE_KEY)}catch{}}
    }
    draw();
    if(mode!=='cloud')return;
    if(!data.advancedConfigured){status.textContent='La IA avanzada todavía no está configurada en el servidor.';return;}
    if(authorized){access.hidden=true;status.textContent='Sesión segura activa. AURA está conectada y lista para conversar.';}
    else{access.hidden=false;status.textContent='Para comenzar, conectá AURA una sola vez.';showLogin();}
  }
  draw();check();
}
document.addEventListener('DOMContentLoaded',render);
})();