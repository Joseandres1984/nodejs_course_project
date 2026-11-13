/* AURA 2.6 — mirada estable durante el diálogo y microexpresiones naturales.
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
  const eyelidCache=new Map();
  const RIG_KEY='aura.face.rig.v25';
  const featureCache=new Map();
  const features={
    femenino:{
      eyes:[{cx:318,cy:249,w:66,h:31},{cx:434,cy:246,w:65,h:30}],
      brows:[{cx:318,cy:213,w:92,h:25},{cx:434,cy:208,w:90,h:25}]
    },
    masculino:{
      eyes:[{cx:294,cy:232,w:63,h:29},{cx:405,cy:230,w:63,h:29}],
      brows:[{cx:291,cy:203,w:88,h:28},{cx:409,cy:201,w:88,h:28}]
    }
  };
  const ZERO={lx:0,ly:0,rx:0,ry:0,lb:0,rb:0};
  let rigTimer=null,rigFrame=null,phaseObserver=null,rigPhase='ready',blinkAmount=0;
  const gaze={...ZERO};
  const rigEnabled=()=>{
    try{return localStorage.getItem(RIG_KEY)!=='off'}catch{return true}
  };

  let timer=null,frameId=null,disposed=false,blinkCount=0;
  const reduce=window.matchMedia?.('(prefers-reduced-motion: reduce)');
  const style=document.createElement('style');
  style.id='aura23Styles';
  style.textContent=[
    '@keyframes aura23Presence{0%,100%{transform:translate3d(0,0,0) scale(1.010) rotate(0deg)}26%{transform:translate3d(.16px,.08px,0) scale(1.011) rotate(.025deg)}52%{transform:translate3d(-.14px,.32px,0) scale(1.012) rotate(-.025deg)}76%{transform:translate3d(.12px,.04px,0) scale(1.011) rotate(.018deg)}}',
    '@keyframes aura23Listen{0%,100%{transform:translate3d(0,0,0) scale(1.011) rotate(.018deg)}50%{transform:translate3d(-.14px,-.20px,0) scale(1.012) rotate(-.018deg)}}',
    '@keyframes aura23Speak{0%,100%{transform:translate3d(0,0,0) scale(1.011) rotate(0deg)}50%{transform:translate3d(.18px,-.24px,0) scale(1.013) rotate(.025deg)}}',
    '.aura23-enabled #v8Stage>img,.aura23-enabled #v8Stage>canvas.aura23-eye-overlay,.aura23-enabled #avatarFrame>img,.aura23-enabled #avatarFrame>canvas.aura23-eye-overlay{animation:aura23Presence 13.5s ease-in-out infinite!important;transform-origin:50% 38%;}',
    '.aura23-enabled #v8Stage[data-phase="listening"]>img,.aura23-enabled #v8Stage[data-phase="listening"]>canvas.aura23-eye-overlay{animation:aura23Listen 10.4s ease-in-out infinite!important;}',
    '.aura23-enabled #v8Stage[data-phase="speaking"]>img,.aura23-enabled #v8Stage[data-phase="speaking"]>canvas.aura23-eye-overlay,.aura23-enabled #avatarFrame.talking>img,.aura23-enabled #avatarFrame.talking>canvas.aura23-eye-overlay{animation:aura23Speak 7.8s ease-in-out infinite!important;}',
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
    if(!active()){
      clearTimeout(timer);timer=null;cancelAnimationFrame(frameId);frameId=null;
      clearRigScheduling();
      for(const key of Object.keys(ZERO))gaze[key]=0;
      blinkAmount=0;clearEyes();return;
    }
    schedule();scheduleRig();
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
  function eyelidPatch(source,eye,g){
    const key=g+':'+eye.cx+':'+eye.cy;
    const cached=eyelidCache.get(key);
    if(cached?.src===source.src)return cached.canvas;
    const w=eye.w+8,h=eye.h+5;
    const x=Math.round(eye.cx-w/2);
    const scratch=document.createElement('canvas');
    scratch.width=w;scratch.height=h;
    const c=scratch.getContext('2d',{alpha:true});
    if(!c)return null;
    // Solo una muestra de piel de la misma foto; se prepara una vez por ojo.
    c.drawImage(source.img,x,eye.skinY,w,7,0,0,w,h);
    c.globalCompositeOperation='destination-in';
    c.save();
    c.translate(w/2,h/2);
    c.scale(1,h/w);
    const mask=c.createRadialGradient(0,0,w*.14,0,0,w*.49);
    mask.addColorStop(0,'rgba(0,0,0,1)');
    mask.addColorStop(.44,'rgba(0,0,0,.79)');
    mask.addColorStop(1,'rgba(0,0,0,0)');
    c.fillStyle=mask;
    c.beginPath();c.arc(0,0,w*.50,0,Math.PI*2);c.fill();
    c.restore();
    c.globalCompositeOperation='source-over';
    eyelidCache.set(key,{src:source.src,canvas:scratch});
    return scratch;
  }
  function drawEye(ctx,source,eye,amount,g){
    const patch=eyelidPatch(source,eye,g);
    if(!patch)return;
    ctx.save();
    // En vez de tapar los ojos por completo, apenas los suaviza durante ~150 ms.
    ctx.globalAlpha=Math.min(.58,Math.max(0,amount)*.58);
    ctx.drawImage(patch,Math.round(eye.cx-patch.width/2),Math.round(eye.cy-patch.height/2));
    ctx.restore();
  }

  function featurePatch(source,g,part,index,def){
    const key=g+':'+part+':'+index;
    const cached=featureCache.get(key);
    if(cached?.src===source.src)return cached.canvas;
    const canvas=document.createElement('canvas');
    canvas.width=def.w;canvas.height=def.h;
    const ctx=canvas.getContext('2d',{alpha:true});
    if(!ctx)return null;
    const x=Math.round(def.cx-def.w/2),y=Math.round(def.cy-def.h/2);
    ctx.drawImage(source.img,x,y,def.w,def.h,0,0,def.w,def.h);
    ctx.globalCompositeOperation='destination-in';
    ctx.save();ctx.translate(def.w/2,def.h/2);ctx.scale(1,def.h/def.w);
    const fade=ctx.createRadialGradient(0,0,def.w*.14,0,0,def.w*.51);
    fade.addColorStop(0,'rgba(0,0,0,.98)');
    fade.addColorStop(.65,'rgba(0,0,0,.89)');
    fade.addColorStop(1,'rgba(0,0,0,0)');
    ctx.fillStyle=fade;ctx.beginPath();ctx.arc(0,0,def.w*.52,0,Math.PI*2);ctx.fill();
    ctx.restore();ctx.globalCompositeOperation='source-over';
    featureCache.set(key,{src:source.src,canvas});
    return canvas;
  }
  function paintRig(ctx,source,g){
    if(!rigEnabled())return;
    const f=features[g];
    if(!f)return;
    const eyeValues=[[gaze.lx,gaze.ly],[gaze.rx,gaze.ry]];
    for(let i=0;i<2;i++){
      const dx=eyeValues[i][0],dy=eyeValues[i][1];
      if(Math.abs(dx)+Math.abs(dy)<.075)continue;
      const def=f.eyes[i],patch=featurePatch(source,g,'eye',i,def);
      if(!patch)continue;
      ctx.save();ctx.globalAlpha=.40;
      ctx.drawImage(patch,def.cx-patch.width/2+dx,def.cy-patch.height/2+dy);
      ctx.restore();
    }
    for(let i=0;i<2;i++){
      const lift=i===0?gaze.lb:gaze.rb;
      if(Math.abs(lift)<.075)continue;
      const def=f.brows[i],patch=featurePatch(source,g,'brow',i,def);
      if(!patch)continue;
      ctx.save();ctx.globalAlpha=.40;
      ctx.drawImage(patch,def.cx-patch.width/2,def.cy-patch.height/2-lift);
      ctx.restore();
    }
  }
  function targetFor(phase){
    // No simula emociones arbitrarias: sólo atención, reflexión y habla.
    if(phase==='listening')return {lx:.06,ly:0,rx:.04,ry:0,lb:.14,rb:.11};
    if(phase==='thinking')return {lx:.50,ly:-.18,rx:.42,ry:-.14,lb:.45,rb:.22};
    if(phase==='speaking')return {lx:.035,ly:0,rx:.025,ry:0,lb:.13,rb:.09};
    if(phase==='error')return {...ZERO};
    const shift=(Math.random()-.5)*.75;
    return {lx:shift,ly:(Math.random()-.5)*.16,rx:shift*.88,ry:(Math.random()-.5)*.16,
      lb:Math.random()*.10,rb:Math.random()*.08};
  }
  function clearRigScheduling(){
    if(rigTimer!==null)clearTimeout(rigTimer);
    if(rigFrame!==null)cancelAnimationFrame(rigFrame);
    rigTimer=null;rigFrame=null;
  }
  function scheduleRig(delay){
    // Sólo se explora suavemente en reposo. Durante la escucha o habla se
    // conserva el contacto visual, evitando sacudidas periódicas.
    if(!active()||!rigEnabled()||rigTimer!==null||rigFrame!==null||rigPhase!=='ready')return;
    rigTimer=setTimeout(()=>{
      rigTimer=null;
      if(!active()||!rigEnabled()||rigPhase!=='ready')return;
      moveRig(targetFor('ready'),true);
    },delay??(3300+Math.random()*3800));
  }
  function moveRig(target,returnHome=false){
    clearRigScheduling();
    if(!active()||!rigEnabled())return;
    const from={...gaze},begin=performance.now(),duration=300+Math.random()*130;
    for(const key of Object.keys(ZERO))target[key]=Math.max(-1.0,Math.min(1.0,Number(target[key])||0));
    const frame=now=>{
      if(!active()||!rigEnabled()){rigFrame=null;return}
      const t=Math.min(1,Math.max(0,(now-begin)/duration));
      const ease=t*t*(3-2*t);
      for(const key of Object.keys(ZERO))gaze[key]=from[key]+(target[key]-from[key])*ease;
      renderBlink(blinkAmount);
      if(t<1)rigFrame=requestAnimationFrame(frame);
      else{
        rigFrame=null;
        if(returnHome){
          rigTimer=setTimeout(()=>{rigTimer=null;moveRig({...ZERO},false)},900+Math.random()*1100);
        }else if(rigPhase==='ready')scheduleRig();
      }
    };
    rigFrame=requestAnimationFrame(frame);
  }
  function setExpression(phase){
    rigPhase=['ready','listening','thinking','speaking','error'].includes(phase)?phase:'ready';
    if(!active()||!rigEnabled())return;
    // Una sola transición para escuchar, pensar y hablar; sin bucles nerviosos.
    moveRig(targetFor(rigPhase),rigPhase==='ready');
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
      paintRig(ctx,source,g);
      if(amount>.015)for(const eye of eyes[g]||eyes.femenino)drawEye(ctx,source,eye,amount,g);
    }
  }
  function blink(){
    if(!active())return;
    const start=performance.now(),duration=125+Math.random()*45;
    blinkCount++;
    function step(now){
      if(!active()){clearEyes();frameId=null;return}
      const t=Math.min(1,(now-start)/duration);
      // Cierre muy corto, con una transición suave sin gestos exagerados.
      const amount=Math.pow(Math.sin(Math.PI*t),2.2);
      blinkAmount=amount;
      renderBlink(amount);
      if(t<1){frameId=requestAnimationFrame(step)}
      else{
        frameId=null;blinkAmount=0;renderBlink(0);
        schedule(Math.random()<.05?320:undefined);
      }
    }
    frameId=requestAnimationFrame(step);
  }
  function schedule(delay){
    if(!active()||timer!==null||frameId!==null)return;
    sourceFor(gender());
    timer=setTimeout(()=>{
      timer=null;blink();
    },delay??(4500+Math.random()*4700));
  }
  function addControl(){
    if($('aura23Gestures'))return;
    const panel=$('auraBrain13')||document.querySelector('.brain-box');
    if(!panel)return;
    const label=document.createElement('label');
    label.style.cssText='display:flex;gap:9px;align-items:flex-start;font-size:12px;color:#caefeb;margin-top:12px;line-height:1.5';
    label.innerHTML='<input id="aura23Gestures" type="checkbox" style="width:18px;height:18px;accent-color:#73f4dc;flex:none" checked><span>Gestos delicados de AURA <small style="display:block;color:#9db7bf">Microparpadeos y respiración muy discreta. Podés desactivarlos.</small></span>';
    panel.append(label);
    const box=$('aura23Gestures');box.checked=enabled();
    box.addEventListener('change',()=>setEnabled(box.checked));
    const eyeToggle=document.createElement('label');
    eyeToggle.style.cssText='display:flex;gap:9px;align-items:flex-start;font-size:12px;color:#caefeb;margin-top:8px;line-height:1.5';
    eyeToggle.innerHTML='<input id="aura25Eyes" type="checkbox" style="width:18px;height:18px;accent-color:#73f4dc;flex:none" checked><span>Mirada y cejas naturales <small style="display:block;color:#9db7bf">Microexpresiones independientes, experimentales y muy discretas.</small></span>';
    panel.append(eyeToggle);
    const eyeBox=$('aura25Eyes');eyeBox.checked=rigEnabled();
    eyeBox.addEventListener('change',()=>{
      try{localStorage.setItem(RIG_KEY,eyeBox.checked?'on':'off')}catch{}
      if(!eyeBox.checked){
        clearRigScheduling();
        for(const key of Object.keys(ZERO))gaze[key]=0;
        renderBlink(blinkAmount);
      }else if(rigPhase==='ready')scheduleRig(200);else setExpression(rigPhase);
    });
  }
  function boot(){
    ensureCanvas('face');
    ensureCanvas('v8Portrait');
    addControl();
    const stage=$('v8Stage');
    const Observer=window.MutationObserver;
    if(stage&&Observer){
      phaseObserver=new Observer(()=>{
        const next=stage.dataset?.phase||'ready';
        if(next!==rigPhase)setExpression(next);
      });
      phaseObserver.observe(stage,{attributes:true,attributeFilter:['data-phase']});
    }
    updateEnabled();
  }
  document.addEventListener('visibilitychange',updateEnabled);
  reduce?.addEventListener?.('change',updateEnabled);
  window.addEventListener('pagehide',()=>{
    disposed=true;clearTimeout(timer);cancelAnimationFrame(frameId);clearRigScheduling();
    phaseObserver?.disconnect?.();clearEyes();
  });
  window.AuraPresence={
    enable:setEnabled,isEnabled:enabled,
    blink:()=>{clearTimeout(timer);timer=null;blink()},
    expression:setExpression,
    gazeEnabled:rigEnabled,
    state:()=>({active:active(),blinkCount,overlays:overlays.size,phase:rigPhase,features:{...gaze},rigEnabled:rigEnabled()})
  };
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});
  else boot();
})();