import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext,Script} from 'node:vm';

const code=readFileSync(new URL('./aura-presence-23.js',import.meta.url),'utf8');
new Script(code);

function createRuntime({reduced=false,switchOff=false}={}){
  const assets={
    './assets/motion/femenino-0.webp':'data:image/webp;base64,mockfemale',
    './assets/motion/masculino-0.webp':'data:image/webp;base64,mockmale'
  };
  let countDraws=0,canvasCount=0;
  const callbacks=new Map(),raf=new Map(),timeouts=new Map();
  let next=0;
  const classes=new Set();
  const ctx=()=>({
    clearRect(){},
    drawImage(){countDraws++},
    save(){},restore(){},translate(){},scale(){},
    createRadialGradient(){return {addColorStop(){}}},
    beginPath(){},arc(){},fill(){},moveTo(){},quadraticCurveTo(){},stroke(){},
    set globalCompositeOperation(_) {},set globalAlpha(_) {},
    set fillStyle(_) {},set strokeStyle(_) {},set lineWidth(_) {},set lineCap(_) {}
  });
  const makeCanvas=()=>({
    width:720,height:960,className:'',setAttribute(){},remove(){},
    getContext(){return ctx()}
  });
  const nodes={};
  for(const id of ['face','v8Portrait']){
    const parent={};
    nodes[id]={
      parentElement:parent, nextElementSibling:null,
      getAttribute:()=>assets['./assets/motion/femenino-0.webp'],
      insertAdjacentElement:()=>{},src:assets['./assets/motion/femenino-0.webp']
    };
  }
  let loadHandler;
  const doc={
    hidden:false,readyState:'loading',
    documentElement:{classList:{toggle:(name,on)=>on?classes.add(name):classes.delete(name)}},
    head:{append(){}},
    createElement:tag=>tag==='canvas'?(canvasCount++,makeCanvas()):({style:{},append(){},set id(v){},get id(){return ''}}),
    getElementById:id=>nodes[id]||null,
    querySelector:selector=>selector==='[data-gender].chosen'?{dataset:{gender:'femenino'}}:null,
    addEventListener:(event,fn)=>{if(event==='DOMContentLoaded')loadHandler=fn;else callbacks.set(event,fn)}
  };
  class FakeImage{
    complete=true;
    naturalWidth=720;
    naturalHeight=960;
    set src(value){this._src=value}
    get src(){return this._src}
  }
  const localStorage={
    getItem:key=>key==='aura.presence.enabled.v23'&&switchOff?'off':null,
    setItem(){}
  };
  const window={
    AURA_ASSETS:assets,
    matchMedia:()=>({matches:reduced,addEventListener(){}}),
    addEventListener(){},
  };
  const context={
    document:doc,window,localStorage,Image:FakeImage,
    Math,performance:{now:()=>0},
    setTimeout:(fn,ms)=>{const n=++next;timeouts.set(n,{fn,ms});return n},
    clearTimeout:id=>timeouts.delete(id),
    requestAnimationFrame:fn=>{const n=++next;raf.set(n,fn);return n},
    cancelAnimationFrame:id=>raf.delete(id)
  };
  runInNewContext(code,context);
  loadHandler();
  return {
    window,classes,timeouts,raf,
    draws:()=>countDraws,
    canvases:()=>canvasCount,
    triggerBlink(){window.AuraPresence.blink();for(const ms of [25,45,90,135,220]){
      const frames=[...raf.values()];raf.clear();
      for(const fn of frames)fn(ms);
    }}
  };
}

test('AURA crea los dos overlays, respeta privacidad y programa gestos naturales',()=>{
  const app=createRuntime();
  assert.equal(app.window.AuraPresence.state().overlays,2);
  assert.equal(app.window.AuraPresence.state().active,true);
  assert.equal(app.classes.has('aura23-enabled'),true);
  assert.ok(app.timeouts.size>0);
  app.triggerBlink();
  assert.ok(app.draws()>0);
});

test('reduce motion apaga los parpadeos y movimiento automático',()=>{
  const app=createRuntime({reduced:true});
  assert.equal(app.window.AuraPresence.state().active,false);
  assert.equal(app.classes.has('aura23-enabled'),false);
  assert.equal(app.timeouts.size,0);
  app.triggerBlink();
  assert.equal(app.draws(),0);
});

test('preferencia off desactiva gestos sin alterar cara a cara ni voz',()=>{
  const app=createRuntime({switchOff:true});
  assert.equal(app.window.AuraPresence.state().active,false);
  assert.equal(app.timeouts.size,0);
});

test('la app sirve AURA 2.5 en Safari y conserva el rostro principal',()=>{
  const server=readFileSync(new URL('./server.mjs',import.meta.url),'utf8');
  const autorun=readFileSync(new URL('./aura-autostart-21.js',import.meta.url),'utf8');
  assert.ok(server.includes('aura-presence-23.js?v=25'));
  assert.ok(server.includes('aura-autostart-21.js?v=25'));
  assert.ok(autorun.includes('CONVERSACIÓN PERSONAL 2.5'));
});

test('parpadeos sucesivos reutilizan los párpados y evitan crear canvas por frame',()=>{
  const app=createRuntime();
  app.triggerBlink();
  const afterFirst=app.canvases();
  app.triggerBlink();
  assert.ok(afterFirst<=4,'dos overlays y dos parches por avatar');
  assert.equal(app.canvases(),afterFirst,'no se reconstruyen los párpados en cada parpadeo');
});

test('AURA mantiene gestos mínimos en lugar de inclinaciones visibles o parpadeos fuertes',()=>{
  assert.ok(code.includes('scale(1.013)'));
  assert.ok(!code.includes('scale(1.026)'));
  assert.ok(code.includes('Math.min(.58,Math.max(0,amount)*.58)'));
  assert.ok(code.includes('4500+Math.random()*4700'));
  assert.ok(code.includes('duration=125+Math.random()*45'));
});

test('los ojos y las cejas responden independientemente al estado de reflexión',()=>{
  const app=createRuntime();
  app.window.AuraPresence.expression('thinking');
  const frames=[...app.raf.values()];
  assert.ok(frames.length>0,'debe iniciar una transición suave');
  app.raf.clear();
  frames[0](510);
  const state=app.window.AuraPresence.state();
  assert.equal(state.phase,'thinking');
  assert.notEqual(state.features.lx,state.features.rx);
  assert.notEqual(state.features.lb,state.features.rb);
  assert.ok(state.features.lb<=1&&state.features.rx<=1,'los desplazamientos son menores a un píxel');
  assert.ok(app.draws()>0,'debe pintar parches faciales independientes');
  const cached=app.canvases();
  app.window.AuraPresence.expression('speaking');
  const speakFrames=[...app.raf.values()];
  app.raf.clear();speakFrames[0](510);
  assert.equal(app.canvases(),cached,'reutiliza los parches de ojos y cejas');
});

test('gestos faciales independientes respetan movimiento reducido y desactivación global',()=>{
  const reduced=createRuntime({reduced:true});
  reduced.window.AuraPresence.expression('thinking');
  assert.equal(reduced.raf.size,0);
  assert.equal(reduced.draws(),0);
  const disabled=createRuntime({switchOff:true});
  disabled.window.AuraPresence.expression('speaking');
  assert.equal(disabled.raf.size,0);
  assert.equal(disabled.draws(),0);
});

test('los gestos no necesitan acceso a cámara, micrófono ni APIs de pago',()=>{
  assert.ok(code.includes('featurePatch(source,g,part,index,def)'));
  assert.ok(code.includes("rigPhase='ready'"));
  assert.ok(!code.includes('getUserMedia('));
  assert.ok(!code.includes('fetch('));
  assert.ok(!code.includes('createObjectURL('));
});
