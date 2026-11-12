/* AURA 1.3: respuesta fiable antes que respuestas inventadas. */
(() => {
'use strict';
const MODE_KEY='aura.brain.mode.v13',CODE_KEY='aura.private.code.v13';
let mode='local',code='';
try{mode=sessionStorage.getItem(MODE_KEY)||'local';code=sessionStorage.getItem(CODE_KEY)||'';}catch{}
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
async function callCloud(state){
  const q=(state?.messages||[]).filter(m=>m.role==='user').at(-1)?.text||'';
  if(!q.trim())throw Error('Falta la consulta.');
  if(!code)throw Error('El cerebro avanzado requiere un código de acceso privado. Todavía no está conectado.');
  const messages=(state?.messages||[]).filter(x=>x&&['user','assistant'].includes(x.role)&&typeof x.text==='string'&&!forbidden.test(normalize(x.text))).slice(-10);
  const image=window.AuraVision?.payload?.() || null;
  const response=await fetch('./api/aura/chat',{method:'POST',cache:'no-store',
    headers:{'Content-Type':'application/json','x-aura-code':code},
    body:JSON.stringify({messages,personality:state.personality,...(image?{image}:{})})});
  const data=await response.json().catch(()=>({}));
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
window.AuraBrain={respond,isCloud:()=>mode==='cloud',isBad,getStatus};
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
    '<input id="auraBrain13Code" type="password" autocomplete="off" placeholder="Solo si conectamos el proveedor" style="display:block;width:100%;padding:12px;margin:8px 0;background:#071722;border:1px solid #39607a;color:white;border-radius:9px"></label>'+
    '<button id="auraBrain13Save" type="button" class="secondary">Guardar código solo por esta sesión</button>'+
    '<p style="font-size:11px;line-height:1.5;color:#9fb7c8">Al usar la nube, se envía el contexto reciente de conversación al proveedor. La modalidad gratuita puede utilizar datos para mejorar sus servicios. No compartas claves de API en este campo.</p></div>';
  brain.parentElement.insertBefore(el,brain);
  const select=$('auraBrain13Mode'),status=$('auraBrain13Status'),access=$('auraBrain13Access');
  select.value=mode;
  function draw(){
    access.hidden=mode!=='cloud';
    if(mode==='local'){status.textContent='Modo local experimental: puede equivocarse. Las respuestas incoherentes se rechazan cuando se detectan; no está garantizada su precisión.';}
    else{status.textContent='Cerebro avanzado seleccionado. Comprobando conexión privada...';}
  }
  select.addEventListener('change',()=>{mode=select.value;try{sessionStorage.setItem(MODE_KEY,mode)}catch{}draw();if(mode==='cloud')check()});
  $('auraBrain13Save').addEventListener('click',()=>{code=$('auraBrain13Code').value.trim().slice(0,120);try{sessionStorage.setItem(CODE_KEY,code)}catch{}status.textContent=code?'Código temporal guardado. Ahora se puede probar una consulta, si el proveedor está configurado.':'No ingresaste un código.';});
  async function check(){const data=await getStatus();if(mode!=='cloud')return;status.textContent=data.advancedConfigured?'Conexión avanzada disponible. Ingresá tu código privado si todavía no lo guardaste.':'La IA avanzada no está configurada en el servidor. Por ahora, seleccioná el modo local experimental o conectemos un proveedor.';}
  draw();if(mode==='cloud')check();
}
document.addEventListener('DOMContentLoaded',render);
})();