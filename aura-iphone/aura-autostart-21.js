/* AURA 2.2 — iniciar con cerebro avanzado y conversación cara a cara.
   Safari puede requerir un gesto real para activar voz y micrófono. */
(() => {
'use strict';
const KEY='aura.voice.autostart.v21';
const $=id=>document.getElementById(id);
let brainReady=false,configured=false,attempted=false,lastStatus=null;
const pref=()=>{try{return localStorage.getItem(KEY)==='on'}catch{return false}};
function setPref(on){try{localStorage.setItem(KEY,on?'on':'off')}catch{}}
function showStatus(text){
  if($('v8Stage')?.dataset.phase==='ready'&&$('v8Status'))$('v8Status').textContent=text;
}
async function tryResumeListening(){
  if(attempted||!brainReady||!pref()||document.visibilityState!=='visible')return;
  const mic=$('v8Mic'),room=$('v8Room');
  if(!mic||!room?.classList.contains('is-open'))return;
  if(!(window.SpeechRecognition||window.webkitSpeechRecognition))return;
  // Solo se intenta reanudar si ya hubo un gesto consentido en una visita anterior
  // y el sistema informa que el permiso de micrófono está concedido.
  if(!navigator.permissions?.query)return;
  let permission;
  try{permission=await navigator.permissions.query({name:'microphone'})}catch{return}
  if(permission?.state!=='granted'||document.visibilityState!=='visible'||!brainReady)return;
  attempted=true;
  // El navegador puede rechazar una activación sin gesto; el botón sigue disponible.
  mic.click();
  setTimeout(()=>{
    if($('v8Stage')?.dataset.phase==='error')
      showStatus('Safari requiere que toques Hablar con AURA para habilitar el micrófono.');
  },900);
}
function render(info){
  lastStatus=info;
  brainReady=!!info.ready;
  configured=!!info.configured;
  const label=document.querySelector('#v8Stage .v8-person span');
  const speaker=$('v8AutoSpeak');
  if(speaker)speaker.checked=true;
  if(label)label.textContent=brainReady?'Cerebro avanzado activo · Español argentino':
    configured?'Cerebro avanzado · Conectá una vez':'Cerebro avanzado sin conexión';
  if(!brainReady){
    showStatus(configured?'Conectá AURA una vez y después entrás directamente.':
      'AURA necesita configurar el cerebro avanzado para conversar.');
    return;
  }
  if($('v8Stage')?.dataset.phase==='ready')
    showStatus('AURA está lista. Hablame tocando una vez el micrófono.');
  tryResumeListening();
}
function boot(){
  const mic=$('v8Mic'),stop=$('v8Stop');
  if(!mic||!$('v8Stage'))return;
  document.querySelector('.v8-label')?.replaceChildren(document.createTextNode('AURA · CONVERSACIÓN PERSONAL 2.2'));
  // Priorizar voz española sin modificar el historial ni activar descargas.
  const accent=$('accent');
  if(accent&&accent.value!=='es-AR'){
    accent.value='es-AR';
    accent.dispatchEvent(new Event('change',{bubbles:true}));
  }
  mic.addEventListener('click',e=>{if(e.isTrusted)setPref(true)},true);
  // Para privacidad: nunca dejamos el reconocimiento activo en segundo plano.
  document.addEventListener('visibilitychange',()=>{
    if(document.visibilityState==='hidden')stop?.click();
    else if(lastStatus?.ready){
      attempted=false;
      showStatus('AURA está lista. Tocá Hablar para reanudar si Safari lo requiere.');
      tryResumeListening();
    }
  });
  window.addEventListener('aura:brain-status',e=>render(e.detail||{}));
  if(window.AuraBrain?.getStatus){
    window.AuraBrain.getStatus().then(s=>{
      render({ready:!!s.sessionActive&&!!s.advancedConfigured&&!!window.AuraBrain.isCloud?.(),configured:!!s.advancedConfigured});
    }).catch(()=>{});
  }
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
