/* AURA 1.5 - visualizador de video facial importado, sin subida al servidor */
(()=>{'use strict';
const $=id=>document.getElementById(id);
const colab='https://colab.research.google.com/github/Joseandres1984/nodejs_course_project/blob/feature/aura-neural-avatar-demo-20261112/aura-iphone/prototypes/AURA_colab_avatar_neuronal.ipynb';
const css=[
'.aura-neural-lab{background:#0d2535;border:1px solid #336a79;border-radius:16px;margin:12px 0 18px;color:#e9fbff}',
'.aura-neural-lab summary{padding:15px;cursor:pointer;font-weight:700;font-size:13px}',
'.aura-neural-inner{padding:0 14px 15px}',
'.aura-neural-inner p{font-size:12px;line-height:1.5;color:#b8cedb;margin:9px 0}',
'.aura-neural-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}',
'.aura-neural-grid button,.aura-neural-grid a{display:flex;align-items:center;justify-content:center;min-height:43px;padding:8px;text-align:center;border:1px solid #407b86;border-radius:10px;background:#123f4a;color:#e9fffb;font-weight:700;font-size:12px;text-decoration:none}',
'.aura-neural-grid button:disabled{opacity:.45}',
'#auraNeuralStatus{display:block;font-size:12px;line-height:1.5;color:#a0efdb;margin-top:10px}',
'#avatarFrame.aura-neural-preview>img#face{visibility:hidden!important}',
'#avatarFrame.aura-neural-preview .frame-bottom{display:none}',
'#avatarFrame>video.aura-neural-video{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;background:#061a21;z-index:1;animation:none!important}',
'#auraNeuralFlag{position:absolute;z-index:4;top:53px;left:12px;background:#041a20ee;color:#bdfbe7;border-radius:6px;border:1px solid #337566;padding:5px 7px;font-size:9px;pointer-events:none}',
'@media(max-width:350px){.aura-neural-grid{grid-template-columns:1fr}}'
].join('');
function boot(){
 const frame=$('avatarFrame');if(!frame||!$('face')||$('auraNeuralLab'))return;
 const style=document.createElement('style');style.textContent=css;document.head.append(style);
 const panel=document.createElement('details');panel.id='auraNeuralLab';panel.className='aura-neural-lab';
 panel.innerHTML='<summary>Laboratorio de avatar · Video facial</summary><div class="aura-neural-inner">'+
 '<p><strong>Movimiento neuronal de prueba:</strong> aquí podés reproducir un MP4 generado en Colab. Es un video pregrabado, no una videollamada en vivo.</p>'+
 '<p>Generá el archivo con el rostro de AURA, descargalo y cargalo desde Archivos del iPhone.</p>'+
 '<div class="aura-neural-grid"><a href="'+colab+'" target="_blank" rel="noopener noreferrer">1 · Generar en Colab</a><button type="button" id="auraNeuralLoad">2 · Cargar MP4</button>'+
 '<button type="button" id="auraNeuralPlay" disabled>Reproducir video</button><button type="button" id="auraNeuralReset" disabled>Volver al avatar 2D</button></div>'+
 '<input type="file" accept="video/mp4,video/webm,.mp4,.webm" id="auraNeuralFile" hidden>'+
 '<span id="auraNeuralStatus" role="status" aria-live="polite">Sin video cargado; se utiliza la animación 2D habitual.</span>'+
 '<p><strong>Privacidad:</strong> el video permanece en este navegador y no se envía a nuestros servidores. Deberás volver a seleccionarlo al cerrar AURA.</p></div>';
 frame.insertAdjacentElement('afterend',panel);
 const input=$('auraNeuralFile'),btn=$('auraNeuralPlay'),reset=$('auraNeuralReset'),label=$('faceMode'),info=$('auraNeuralStatus');
 let src=null,active=false;
 const video=document.createElement('video');video.id='auraNeuralVideo';video.className='aura-neural-video';video.controls=true;video.playsInline=true;video.preload='metadata';video.hidden=true;video.setAttribute('playsinline','');frame.append(video);
 const flag=document.createElement('span');flag.id='auraNeuralFlag';flag.textContent='VIDEO IMPORTADO · NO ES EN VIVO';flag.hidden=true;frame.append(flag);
 const message=s=>info.textContent=s;
 function original(){video.pause();video.hidden=true;flag.hidden=true;active=false;frame.classList.remove('aura-neural-preview');if(label?.dataset.prevMode)label.textContent=label.dataset.prevMode;btn.textContent='Reproducir video';btn.disabled=!src;reset.disabled=true}
 function preview(){if(!src)return;video.hidden=false;flag.hidden=false;active=true;frame.classList.add('aura-neural-preview');if(label){label.dataset.prevMode||=label.textContent;label.textContent='VIDEO MP4'}btn.disabled=false;reset.disabled=false}
 $('auraNeuralLoad').addEventListener('click',()=>input.click());
 input.addEventListener('change',()=>{
  const file=input.files?.[0];if(!file)return;
  if(!/\.(mp4|webm)$/i.test(file.name)||!['','video/mp4','video/webm'].includes(file.type)){message('Elegí un MP4 o WebM.');input.value='';return}
  if(file.size<1024||file.size>120*1048576){message('Tamaño permitido: entre 1 KB y 120 MB.');input.value='';return}
  video.pause();if(src)URL.revokeObjectURL(src);src=URL.createObjectURL(file);video.src=src;video.load();preview();input.value='';
  message('Video local elegido: '+file.name.slice(0,60)+' ('+(file.size/1048576).toFixed(1)+' MB). No se subió a internet.');
 });
 video.addEventListener('loadedmetadata',()=>message('Video listo: '+Math.round(video.duration||0)+' segundos. Tocá Reproducir.'));
 video.addEventListener('error',()=>message('Formato no compatible. En iPhone usá MP4 H.264 con audio AAC.'));
 video.addEventListener('play',()=>btn.textContent='Pausar video');
 video.addEventListener('pause',()=>btn.textContent='Reproducir video');
 video.addEventListener('ended',()=>btn.textContent='Reproducir video');
 btn.addEventListener('click',async()=>{if(!src)return;preview();if(!video.paused){video.pause();return}try{if(video.ended)video.currentTime=0;await video.play()}catch{message('Safari bloqueó reproducción. Tocá ▶ sobre el video.')}});
 reset.addEventListener('click',()=>{original();message('Volviste al avatar 2D; el MP4 sigue disponible hasta cerrar AURA.')});
 $('faceSwitch')?.addEventListener('click',()=>{if(active)original()});
 document.querySelectorAll('[data-gender]').forEach(b=>b.addEventListener('click',()=>{if(active)original()}));
 document.addEventListener('visibilitychange',()=>{if(document.hidden)video.pause()});
 window.addEventListener('pagehide',()=>{video.pause();if(src)URL.revokeObjectURL(src)});
 window.AuraNeuralLab={isPreview:()=>active,reset:original};
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();