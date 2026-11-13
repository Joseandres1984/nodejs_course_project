/* AURA 2.3 — presencia facial sutil sobre los fotogramas originales.
   Parpadeos breves y postura delicada. Sin cámara, librerías ni video externo. */
(() => {
  'use strict';
  const KEY='aura.presence.enabled.v23';
  const $=id=>document.getElementById(id);
  const supportsMotion=()=>!window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
  const enabled=()=>{
    try{return localStorage.getItem(KEY)!=='off'}catch{return true}
  };
  const eyes={
    femenino:[
      {cx:319,cy:249,w:66,h:29,skinY:268},
      {cx:435,cy:245,w:65,h:29,skinY:264}
    ],
    masculino:[
      {cx:294,cy:232,w:62,h:26,skinY:252},
      {cx:404,cy:230,w:60,h:26,skinY:250}
    ]
  };
  const overlays=new Map();
  const sources=new Map();
  let timer=null,frameId=null,disposed=false,blinkCount=0;
  const reduce=window.matchMedia?.('(prefers-reduced-motion: reduce)');
  const style=document.createElement('style');
  style.id='aura23Styles';
  style.textContent=[
    '@keyframes aura23Presence{0%,100%{transform:translate3d(0,0,0) scale(1.017) rotate(0deg)}26%{transform:translate3d(.6px,.2px,0) scale(1.021) rotate(.12deg)}52%{transform:translate3d(-.6px,1px,0) scale(1.023) rotate(-.1deg)}76%{transform:translate3d(.4px,.1px,0) scale(1.019) rotate(.09deg)}}',
    '@keyframes aura23Listen{0%,100%{transform:translate3d(0,0,0) scale(1.023) rotate(.09deg)}50%{transform:translate3d(-.4px,-.5px,0) scale(1.025) rotate(-.1deg)}}',
    '@keyframes aura23Speak{0%,100%{transform:translate3d(0,0,0) scale(1.021) rotate(0deg)}50%{transform:translate3d(.7px,-.8px,0) scale(1.026) rotate(.13deg)}}',
    '.aura23-enabled #v8Stage>img,.aura23-enabled #v8Stage>canvas.aura23-eye-overlay,.aura23-enabled #avatarFrame>img,.aura23-enabled #avatarFrame>canvas.aura23-eye-overlay{animation:aura23Presence 8.4s ease-in-out infinite!important;transform-origin:50% 38%;}',
    '.aura23-enabled #v8Stage[data-phase="listening"]>img,.aura23-enabled #v8Stage[data-phase="listening"]>canvas.aura23-eye-overlay{animation:aura23Listen 6.8s ease-in-out infinite!important;}',
    '.aura23-enabled #v8Stage[data-phase="speaking"]>img,.aura23-enabled #v8Stage[data-phase="speaking"]>canvas.aura23-eye-overlay,.aura23-enabled #avatarFrame.talking>img,.aura23-enabled #avatarFrame.talking>canvas.aura23-eye-overlay{animation:aura23Speak 3.7s ease-in-out infinite!important;}',
    '#v8Stage>canvas.aura23-eye-overlay,#avatarFrame>canvas.aura23-eye-overlay{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;object-position:center 31%;pointer-events:none;z-index:1;opacity:1;}',
    '#avatarFrame>canvas.aura23-eye-overlay{object-position:center 34%;}',
    '@media(prefers-reduced-motion:reduce){.aura23-enabled #v8Stage>img,.aura23-enabled #v8Stage>canvas.aura23-eye-overlay,.aura23-enabled #avatarFrame>img,.aura23-enabled #avatarFrame>canvas.aura23-eye-overlay{animation:none!important;}}'
  ].join('\n');
  document.head.append(style);

  function setEnabled(value){
    try{localStorage.setItem(KEY,value?'on':'off')}catch{}
    updateEnabled();
  }
  function active(){
    return !disposed&&enabled()&&supportsMotion()&&!document.hidden;
  }
  function updateEnabled(){
    document.documentElement.classList.toggle('aura23-enabled',enabled()&&supportsMotion());
    if(!active()){clearTimeout(timer);timer=null;cancelAnimationFrame(frameId);frameId=null;clearEyes();return}
    schedule();
  }
  function gender(){
    return document.querySelector('[data-gender].chosen')?.dataset.gender||'femenino';
  }
  function sourceFor(g){
    const src=window.AURA_ASSETS?.['./assets/motion/'+g+'-0.webp'];
    if(!src)return null;
    const cached=sources.get(g);
    if(cached?.src===src)return cached;
    const img=new Image();
    const entry={img,src,ready:false};
    img.onload=()=>{entry.ready=true; if(active())schedule()};
    img.onerror=()=>{entry.ready=false};
    img.src=src;
    sources.set(g,entry);
    if(img.complete&&img.naturalWidth)entry.ready=true;
    return entry;
  }
  function ensureCanvas(id){
    const img=$(id);
    if(!img||!img.parentElement)return null;
    const existing=overlays.get(id);
    if(existing&&existing.img===img)return existing;
    existing?.canvas?.remove();
    const canvas=document.createElement('canvas');
    canvas.className='aura23-eye-overlay';
    canvas.setAttribute('aria-hidden','true');
    canvas.width=720;canvas.height=960;
    const ghost=img.nextElementSibling?.classList.contains('aura-motion-ghost')?img.nextElementSibling:null;
    (ghost||img).insertAdjacentElement('afterend',canvas);
    const info={img,canvas,ctx:canvas.getContext('2d',{alpha:true})};
    if(!info.ctx){canvas.remove();return null}
    overlays.set(id,info);
    return info;
  }
  function clearEyes(){
    for(const item of overlays.values())item.ctx?.clearRect(0,0,item.canvas.width,item.canvas.height);
  }
  function drawEye(ctx,source,eye,amount,g){
    const w=eye.w+18,h=eye.h+12,x=Math.round(eye.cx-w/2),y=Math.round(eye.cy-h/2);
    const scratch=document.createElement('canvas');
    scratch.width=w;scratch.height=h;
    const c=scratch.getContext('2d',{alpha:true});
    if(!c)return;
    // Reconstruir párpados desde la propia textura de piel del rostro.
    c.drawImage(source,x,eye.skinY,w,9,0,0,w,h);
    c.globalCompositeOperation='destination-in';
    c.save();
    c.translate(w/2,h/2);c.scale(1,h/w);
    const mask=c.createRadialGradient(0,0,w*.21,0,0,w*.50);
    mask.addColorStop(0,'rgba(0,0,0,1)');
    mask.addColorStop(.62,'rgba(0,0,0,.93)');
    mask.addColorStop(1,'rgba(0,0,0,0)');
    c.fillStyle=mask;c.beginPath();c.arc(0,0,w*.51,0,Math.PI*2);c.fill();
    c.restore();
    c.globalCompositeOperation='source-over';
    ctx.save();
    ctx.globalAlpha=Math.min(.98,amount);
    ctx.drawImage(scratch,x,y);
    if(amount>.44){
      ctx.globalAlpha=Math.pow(amount,2)*.53;
      ctx.strokeStyle=g==='femenino'?'#76564b':'#55463d';
      ctx.lineWidth=1.3;ctx.lineCap='round';
      ctx.beginPath();
      ctx.moveTo(eye.cx-eye.w*.34,eye.cy+2);
      ctx.quadraticCurveTo(eye.cx,eye.cy+5,eye.cx+eye.w*.34,eye.cy+2);
      ctx.stroke();
    }
    ctx.restore();
  }
  function renderBlink(amount){
    if(!active())return;
    const g=gender(),source=sourceFor(g);
    if(!source?.ready)return;
    for(const id of ['face','v8Portrait']){
      const entry=ensureCanvas(id);
      if(!entry)continue;
      const {img,canvas,ctx}=entry;
      // No alterar avatares externos o fotos personalizadas.
      if(!Object.values(window.AURA_ASSETS||{}).includes(img.getAttribute('src'))){
        ctx.clearRect(0,0,canvas.width,canvas.height);
        continue;
      }
      if(canvas.width!==source.img.naturalWidth||canvas.height!==source.img.naturalHeight){
        canvas.width=source.img.naturalWidth;
        canvas.height=source.img.naturalHeight;
      }
      ctx.clearRect(0,0,canvas.width,canvas.height);
      for(const eye of eyes[g]||eyes.femenino)drawEye(ctx,source.img,eye,amount,g);
    }
  }
  function blink(){
    if(!active())return;
    const start=performance.now(),duration=145+Math.random()*50;
    blinkCount++;
    function step(now){
      if(!active()){clearEyes();frameId=null;return}
      const t=Math.min(1,(now-start)/duration);
      // Dos cierres suaves, con una apertura breve y sin pulso robótico.
      const amount=Math.pow(Math.sin(Math.PI*t),1.7);
      renderBlink(amount);
      if(t<1){frameId=requestAnimationFrame(step)}
      else{
        frameId=null;clearEyes();
        schedule(Math.random()<.16?190:undefined);
      }
    }
    frameId=requestAnimationFrame(step);
  }
  function schedule(delay){
    if(!active()||timer!==null||frameId!==null)return;
    sourceFor(gender());
    timer=setTimeout(()=>{
      timer=null;blink();
    },delay??(2400+Math.random()*4300));
  }
  function addControl(){
    if($('aura23Gestures'))return;
    const panel=$('auraBrain13')||document.querySelector('.brain-box');
    if(!panel)return;
    const label=document.createElement('label');
    label.style.cssText='display:flex;gap:9px;align-items:flex-start;font-size:12px;color:#caefeb;margin-top:12px;line-height:1.5';
    label.innerHTML='<input id="aura23Gestures" type="checkbox" style="width:18px;height:18px;accent-color:#73f4dc;flex:none" checked><span>Gestos delicados de AURA <small style="display:block;color:#9db7bf">Parpadeos y movimiento sutil al escuchar, pensar y hablar. Podés desactivarlos.</small></span>';
    panel.append(label);
    const box=$('aura23Gestures');box.checked=enabled();
    box.addEventListener('change',()=>setEnabled(box.checked));
  }
  function boot(){
    ensureCanvas('face');
    ensureCanvas('v8Portrait');
    addControl();
    updateEnabled();
  }
  document.addEventListener('visibilitychange',updateEnabled);
  reduce?.addEventListener?.('change',updateEnabled);
  window.addEventListener('pagehide',()=>{disposed=true;clearTimeout(timer);cancelAnimationFrame(frameId);clearEyes()});
  window.AuraPresence={enable:setEnabled,isEnabled:enabled,blink:()=>{clearTimeout(timer);timer=null;blink()},state:()=>({active:active(),blinkCount,overlays:overlays.size})};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});
  else boot();
})();