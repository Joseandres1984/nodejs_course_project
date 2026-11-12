/* AURA 1.7 - Cámara en conversación. Transmite solo una captura consentida. */
(()=>{
'use strict';
const $=id=>document.getElementById(id);
const css=[
'.j17-bar{margin:9px 0 3px;display:flex;gap:8px}',
'.j17-bar button{width:100%;min-height:42px;background:#133d48;border:1px solid #44838c;border-radius:12px;color:#dffcf5;font-weight:750;font-size:13px}',
'.j17-panel{margin:8px 0;padding:13px;background:#102532;border:1px solid #477986;border-radius:14px;color:#dafff9}',
'.j17-panel p{font-size:12px;line-height:1.45;color:#bdd6d9;margin:5px 0 10px}',
'.j17-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}',
'.j17-grid button{min-height:42px;padding:8px;background:#15414e;border:1px solid #49878d;border-radius:10px;color:#eafffb;font-weight:650;font-size:12px}',
'.j17-panel button:disabled{opacity:.45}',
'.j17-panel textarea{display:block;width:100%;min-height:60px;max-height:110px;resize:vertical;background:#071c2a;color:#e9fcf6;border:1px solid #3e6974;border-radius:9px;padding:9px;margin:8px 0}',
'#j17Send{width:100%;margin:6px 0;min-height:42px;background:#6eefd8;color:#052f34;font-weight:850;border:0;border-radius:10px}',
'#j17Status{min-height:20px;margin-top:7px;color:#aef2db;font-size:12px;line-height:1.5}',
'.v8-stage #j17Visual{position:absolute;z-index:5;inset:0;background:#061826;overflow:hidden}',
'.v8-stage #j17Visual video,.v8-stage #j17Visual img{width:100%;height:100%;object-fit:contain;animation:none!important;transform:none!important;background:#061826}',
'#j17Flag{position:absolute;top:12px;left:12px;color:#bcfbe8;background:#061c27cc;border:1px solid #3b8b82;border-radius:7px;padding:6px 9px;font-size:10px;font-weight:700;z-index:2}'
].join('');
function boot(){
 const stage=$('v8Stage');
 if(!stage||$('j17Toggle'))return;
 const style=document.createElement('style');style.textContent=css;document.head.append(style);
 document.title='AURA 1.7 · Cámara cara a cara';
 const version=document.querySelector('.intro .eyebrow');if(version)version.textContent='EDICIÓN PERSONAL · iPHONE 1.7';
 const roomVersion=document.querySelector('.v8-label');if(roomVersion)roomVersion.textContent='AURA · CONVERSACIÓN CARA A CARA 1.7';
 const bar=document.createElement('div');bar.className='j17-bar';bar.innerHTML='<button id="j17Toggle" type="button">◉ Mirar con AURA</button>';
 stage.insertAdjacentElement('afterend',bar);
 const panel=document.createElement('section');panel.id='j17Panel';panel.className='j17-panel';panel.hidden=true;
 panel.innerHTML='<p>Mostrale algo a AURA. La cámara solo se activa con permiso; no enviamos video continuo.</p>'+
 '<div class="j17-grid"><button id="j17Open" type="button">Abrir cámara</button><button id="j17Choose" type="button">Elegir foto</button>'+
 '<button id="j17Shot" type="button" disabled>Capturar imagen</button><button id="j17Clear" type="button">Cerrar cámara</button></div>'+
 '<input id="j17Input" type="file" accept="image/*" hidden>'+
 '<label for="j17Question" style="display:block;font-size:12px;margin-top:9px">¿Qué querés saber?</label>'+
 '<textarea id="j17Question" maxlength="850">AURA, describí lo que estoy mostrando y decime lo más importante.</textarea>'+
 '<button id="j17Send" type="button" disabled>Analizar imagen y responderme</button>'+
 '<div id="j17Status" role="status" aria-live="polite">Sin imagen seleccionada.</div>'+
 '<p style="font-size:10px">La imagen solo se envía al tocar Analizar. Requiere el modo «Avanzado por internet».</p>';
 bar.insertAdjacentElement('afterend',panel);
 const wrap=document.createElement('div');wrap.id='j17Visual';wrap.hidden=true;
 const flag=document.createElement('span');flag.id='j17Flag';flag.textContent='CÁMARA LOCAL';
 const video=document.createElement('video');video.id='j17Video';video.autoplay=true;video.muted=true;video.playsInline=true;video.setAttribute('playsinline','');
 const photo=document.createElement('img');photo.id='j17Photo';photo.alt='Captura lista para analizar';photo.hidden=true;
 wrap.append(flag,video,photo);stage.append(wrap);
 let stream=null,active=false,hasPhoto=false,busy=false,live=false;
 const status=t=>$('j17Status').textContent=t;
 function stopCamera(){
  const old=stream;stream=null;live=false;
  video.pause();video.srcObject=null;
  if(old)for(const track of old.getTracks())track.stop();
  $('j17Shot').disabled=true;
 }
 function hidePhoto(){wrap.hidden=true;photo.hidden=true;photo.removeAttribute('src');video.hidden=false;}
 function discard(){
  stopCamera();hidePhoto();hasPhoto=false;$('j17Send').disabled=true;
  window.AuraVision?.clear?.();
 }
 function close(){
  discard();active=false;panel.hidden=true;$('j17Toggle').textContent='◉ Mirar con AURA';
 }
 function show(){
  active=true;panel.hidden=false;$('j17Toggle').textContent='✕ Cerrar visión';
  status('Podés abrir la cámara o elegir una foto. Solo se envía al tocar Analizar.');
 }
 $('j17Toggle').addEventListener('click',()=>active?close():show());
 async function openCamera(){
  if(busy)return;busy=true;discard();
  if(!navigator.mediaDevices?.getUserMedia){status('No se puede abrir cámara aquí. Usá «Elegir foto» o Safari.');busy=false;return;}
  status('Solicitando permiso de cámara…');
  try{
   const got=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:'environment'},width:{ideal:1280}},audio:false});
   if(!active){got.getTracks().forEach(t=>t.stop());return;}
   stream=got;video.srcObject=got;photo.hidden=true;wrap.hidden=false;flag.textContent='CÁMARA LOCAL · NO ENVIADA';
   await video.play();live=true;$('j17Shot').disabled=false;
   status('Cámara activa únicamente en tu teléfono. Tocá «Capturar imagen».');
  }catch(e){
   stopCamera();hidePhoto();
   const m={NotAllowedError:'No autorizaste la cámara.',NotFoundError:'No encontré cámara.',NotReadableError:'Otra app está usando la cámara.',SecurityError:'Safari bloqueó la cámara.'};
   status((m[e?.name]||'No se pudo abrir la cámara.')+' También podés elegir una foto.');
  }finally{busy=false;}
 }
 async function prepare(file){
  if(!file||busy)return;busy=true;stopCamera();hasPhoto=false;$('j17Send').disabled=true;
  status('Preparando la captura en el iPhone…');
  try{
   const ok=await window.AuraVision?.prepareFile?.(file);
   const src=$('auraVisionPreview')?.getAttribute('src');
   if(!ok||!src){status($('auraVisionStatus')?.textContent||'No pude preparar la foto.');return;}
   photo.src=src;photo.hidden=false;video.hidden=true;wrap.hidden=false;flag.textContent='FOTO LISTA · NO ENVIADA';
   hasPhoto=true;$('j17Send').disabled=false;
   status('Foto preparada. Modificá la pregunta y tocá Analizar cuando quieras enviarla.');
  }catch(e){status('No pude preparar esta foto: '+String(e?.message||e));}
  finally{busy=false;}
 }
 $('j17Open').addEventListener('click',openCamera);
 $('j17Choose').addEventListener('click',()=>$('j17Input').click());
 $('j17Input').addEventListener('change',e=>{const f=e.target.files?.[0];e.target.value='';prepare(f)});
 $('j17Shot').addEventListener('click',async()=>{
  if(!live||busy||!video.videoWidth){status('La cámara todavía no está lista.');return;}
  const w=video.videoWidth,h=video.videoHeight,scale=Math.min(1,1280/Math.max(w,h));
  const c=document.createElement('canvas');c.width=Math.max(1,Math.round(w*scale));c.height=Math.max(1,Math.round(h*scale));
  const ctx=c.getContext('2d');if(!ctx){status('No pude capturar la imagen.');return;}
  ctx.drawImage(video,0,0,c.width,c.height);
  const blob=await new Promise(resolve=>c.toBlob(resolve,'image/jpeg',.82));
  if(!blob){status('No pude capturar la imagen; probá elegir una foto.');return;}
  await prepare(new File([blob],'aura-foto.jpg',{type:'image/jpeg'}));
 });
 $('j17Clear').addEventListener('click',()=>{discard();status('Cámara apagada. Foto descartada.');});
 $('j17Send').addEventListener('click',()=>{
  if(!hasPhoto){status('Elegí o capturá una imagen.');return;}
  if(!window.AuraBrain?.isCloud?.()){status('Seleccioná Cerebro avanzado en la pantalla principal. La imagen no se envió.');return;}
  const form=$('v8Form'),field=$('v8Input');
  if(!form||!field){status('No encontré la conversación. Recargá Safari.');return;}
  if(!window.AuraVision?.arm?.()){status('No pude adjuntar esta foto.');return;}
  field.value=$('j17Question').value.trim()||'AURA, explicame qué ves en esta imagen.';
  form.requestSubmit();
  stopCamera();hidePhoto();hasPhoto=false;$('j17Send').disabled=true;
  active=false;panel.hidden=true;$('j17Toggle').textContent='◉ Mirar con AURA';
 });
 $('v8Close')?.addEventListener('click',close);
 $('v8Stop')?.addEventListener('click',stopCamera);
 document.addEventListener('visibilitychange',()=>{if(document.hidden)stopCamera()});
 window.addEventListener('pagehide',stopCamera);
 window.AuraJarvis={show,close,stopCamera};
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();