/* AURA 1.6: visión multimodal; imagen temporal, sin persistencia local */
(()=>{
'use strict';
const $=id=>document.getElementById(id);
let prepared=null,processing=false,armed=false;
const css=[
'.aura-vision{margin:14px 0 18px;padding:0;background:linear-gradient(130deg,#0f2938,#0a1a29);border:1px solid #3e777b;border-radius:18px;overflow:hidden}',
'.aura-vision summary{cursor:pointer;list-style:none;padding:16px;font-weight:750;font-size:15px;color:#d7fffa;display:flex;justify-content:space-between;gap:10px}',
'.aura-vision summary::-webkit-details-marker{display:none}',
'.aura-vision summary::after{content:"⌄";color:#77ebdd;font-size:20px}',
'.aura-vision[open] summary::after{content:"⌃"}',
'.aura-vision-content{padding:0 15px 16px}',
'.aura-vision .introline{font-size:12px;line-height:1.55;color:#c0d6df;margin:3px 0 13px}',
'.aura-vision-grid{display:grid;grid-template-columns:1fr 1fr;gap:9px}',
'.aura-vision-grid button{font-size:12px;line-height:1.4;padding:11px 9px;border:1px solid #468c91;border-radius:11px;background:#16404e;color:#e8fffb;min-height:43px;font-weight:650}',
'.aura-vision-grid button:disabled{opacity:.48}',
'#auraVisionQuestion{display:block;width:100%;min-height:72px;resize:vertical;background:#071b2a;color:#f2ffff;border:1px solid #416873;border-radius:12px;padding:12px;margin:12px 0;font:inherit;font-size:13px}',
'#auraVisionPreview{display:block;max-height:260px;max-width:100%;width:auto;margin:10px auto;border-radius:12px;border:1px solid #3b7582;object-fit:contain}',
'#auraVisionGo{width:100%;background:#73f6d9;color:#062f34;border:0;border-radius:12px;font-weight:800;font-size:14px;padding:13px;margin-top:4px}',
'#auraVisionGo:disabled{opacity:.5}',
'#auraVisionStatus{display:block;color:#b0ead8;font-size:12px;line-height:1.55;margin:9px 0;min-height:18px}',
'#auraVisionRemove{background:transparent;color:#fbc9cc;border:1px solid #986169;border-radius:8px;font-size:12px;padding:7px 9px;margin-top:3px}',
'.aura-vision small{font-size:11px;color:#8dabb7;line-height:1.55;display:block;margin-top:9px}',
'@media(max-width:350px){.aura-vision-grid{grid-template-columns:1fr}}'
].join('');
function setStatus(message){const el=$('auraVisionStatus');if(el)el.textContent=message;}
function clear(){
 prepared=null;armed=false;
 const preview=$('auraVisionPreview'),remove=$('auraVisionRemove'),send=$('auraVisionGo');
 if(preview){preview.removeAttribute('src');preview.hidden=true;}
 if(remove)remove.hidden=true;
 if(send)send.disabled=true;
 for(const id of ['auraVisionCamera','auraVisionFile']){const input=$(id);if(input)input.value='';}
}
function payload(){if(!armed||!prepared)return null;armed=false;return {mimeType:prepared.mimeType,data:prepared.data};}
function onSent(){
 clear();
 setStatus('Análisis recibido. AURA ya tiene la imagen y respondió en la conversación. La foto no se guardó en el historial.');
}
async function compress(file){
 if(file.size>16*1048576)throw Error('La fotografía supera 16 MB. Elegí otra.');
 if(!file.type.startsWith('image/')&&!/\.(jpg|jpeg|png|webp|heic|heif)$/i.test(file.name))throw Error('Solo imágenes: JPG, PNG, WebP o fotos de iPhone compatibles.');
 const src=URL.createObjectURL(file);
 try{
   const img=new Image();
   await new Promise((resolve,reject)=>{
    img.onload=resolve;img.onerror=()=>reject(Error('Safari no puede leer la foto. Exportala como JPG e intentá de nuevo.'));img.src=src;
   });
   const w=img.naturalWidth,h=img.naturalHeight;
   if(!w||!h||w*h>1e8)throw Error('La resolución de la fotografía no es compatible.');
   const scale=Math.min(1,1280/Math.max(w,h));
   const canvas=document.createElement('canvas');
   canvas.width=Math.max(1,Math.round(w*scale));
   canvas.height=Math.max(1,Math.round(h*scale));
   const ctx=canvas.getContext('2d',{alpha:false});
   if(!ctx)throw Error('No puedo preparar la imagen en este navegador.');
   ctx.drawImage(img,0,0,canvas.width,canvas.height);
   const url=canvas.toDataURL('image/jpeg',0.78);
   const data=url.split(',')[1];
   if(!data||data.length>4*1048576)throw Error('La foto es demasiado grande después de comprimirla.');
   return {mimeType:'image/jpeg',data,preview:url,width:canvas.width,height:canvas.height};
 }finally{URL.revokeObjectURL(src);}
}
async function choose(file){
 if(!file)return;
 if(processing)return;
 processing=true;clear();setStatus('Preparando imagen en el iPhone…');
 try{
   const resized=await compress(file);
   prepared={mimeType:resized.mimeType,data:resized.data};
   const preview=$('auraVisionPreview');
   preview.src=resized.preview;preview.hidden=false;
   $('auraVisionRemove').hidden=false;$('auraVisionGo').disabled=false;
   setStatus('Foto preparada ('+resized.width+' × '+resized.height+'). Todavía no se envió. Solo sale de tu teléfono cuando tocás Analizar.');
 }catch(e){clear();setStatus(String(e.message||e));}
 finally{processing=false;}
}
function init(){
 const brain=document.querySelector('.brain-box');
 if(!brain||$('auraVision'))return;
 const style=document.createElement('style');style.textContent=css;document.head.append(style);
 const panel=document.createElement('details');panel.id='auraVision';panel.className='aura-vision';
 panel.innerHTML='<summary><span>◉ AURA VISIÓN — Mostrame algo</span><span aria-hidden="true">●</span></summary>'+
 '<div class="aura-vision-content"><p class="introline">Sacá una foto o elegí una imagen para que AURA la analice con Gemini y te responda en español. El avatar puede leer la respuesta en voz alta.</p>'+
 '<div class="aura-vision-grid"><button type="button" id="auraVisionTake">📷 Sacar foto</button><button type="button" id="auraVisionChoose">▧ Elegir imagen</button></div>'+
 '<input type="file" accept="image/*" capture="environment" hidden id="auraVisionCamera">'+
 '<input type="file" accept="image/*" hidden id="auraVisionFile">'+
 '<img id="auraVisionPreview" alt="Imagen elegida para analizar" hidden>'+
 '<button type="button" id="auraVisionRemove" hidden>Quitar foto</button>'+
 '<label for="auraVisionQuestion" style="display:block;font-size:12px;margin-top:12px;color:#cbede8">¿Qué querés saber?</label>'+
 '<textarea id="auraVisionQuestion" maxlength="900">Describí qué ves en esta imagen y decime los detalles importantes.</textarea>'+
 '<button type="button" id="auraVisionGo" disabled>Analizar con AURA</button>'+
 '<span id="auraVisionStatus" role="status" aria-live="polite">Ninguna imagen seleccionada.</span>'+
 '<small>Privacidad: la imagen se reduce en el iPhone y se envía a Gemini solamente cuando tocás Analizar. No queda guardada en la memoria ni en Render. Para usar esta función elegí «Avanzado por internet» en Cerebro de AURA. El proveedor procesa la imagen según sus condiciones.</small></div>';
 brain.insertAdjacentElement('afterend',panel);
 $('auraVisionTake').addEventListener('click',()=>$('auraVisionCamera').click());
 $('auraVisionChoose').addEventListener('click',()=>$('auraVisionFile').click());
 $('auraVisionCamera').addEventListener('change',e=>choose(e.target.files?.[0]));
 $('auraVisionFile').addEventListener('change',e=>choose(e.target.files?.[0]));
 $('auraVisionRemove').addEventListener('click',()=>{clear();setStatus('Imagen eliminada. No se envió.')});
 $('auraVisionGo').addEventListener('click',()=>{
  if(!prepared){setStatus('Primero elegí una foto.');return;}
  if(!window.AuraBrain?.isCloud?.()){
    setStatus('Para analizar imágenes, entrá en «Cerebro de AURA» y elegí «Avanzado por internet». Tu foto no se envió.');
    return;
  }
  const txt=($('auraVisionQuestion').value||'').trim()||'Explicame qué aparece en esta imagen.';
  const input=$('messageInput'),form=$('messageForm');
  if(!input||!form){setStatus('No encuentro el chat de AURA. Recargá Safari.');return;}
  input.value=txt;armed=true;form.requestSubmit();
  setStatus('Consulta enviada. La respuesta aparecerá en Conversación. Si la red falla, conservaremos la foto para reintentar.');
 });
 window.AuraVision={payload,onSent,clear};
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();