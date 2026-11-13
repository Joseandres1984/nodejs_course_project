import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
const startup=readFileSync(new URL('./aura-autostart-21.js',import.meta.url),'utf8');

function environment({consent=false,permission='granted',authorized=true,configured=true}={}){
  const saved=new Map(consent?[['aura.voice.autostart.v21','on']]:[]);
  const handlers=new Map();
  const add=(key,fn)=>{const v=handlers.get(key)||[];v.push(fn);handlers.set(key,v)};
  const emit=(key,data={})=>(handlers.get(key)||[]).forEach(fn=>fn(data));
  let clicks=0;
  const mic={
    addEventListener:(type,fn)=>add('mic:'+type,fn),
    click(){clicks++;emit('mic:click',{isTrusted:false})}
  };
  const stage={dataset:{phase:'ready'}};
  const status={textContent:''};
  const faceLabel={textContent:''};
  const speaker={checked:false};
  const accent={value:'en-US',dispatchEvent:()=>{}};
  const label={replaceChildren(n){this.text=n.text}};
  const elements={v8Mic:mic,v8Room:{classList:{contains:()=>true}},v8Stage:stage,v8Status:status,v8AutoSpeak:speaker,accent,v8Stop:{click(){} }};
  const document={
    readyState:'complete',
    visibilityState:'visible',
    getElementById:id=>elements[id]||null,
    querySelector:sel=>({'.v8-label':label,'#v8Stage .v8-person span':faceLabel}[sel]||null),
    createTextNode:text=>({text}),
    addEventListener:(type,fn)=>add('document:'+type,fn)
  };
  const window={
    SpeechRecognition:function(){},
    AuraBrain:{getStatus:async()=>({sessionActive:authorized,advancedConfigured:configured}),isCloud:()=>true},
    addEventListener:(type,fn)=>add('window:'+type,fn)
  };
  const navigator={permissions:{query:async()=>({state:permission})}};
  const localStorage={getItem:key=>saved.get(key)||null,setItem:(key,val)=>saved.set(key,String(val))};
  runInNewContext(startup,{window,document,navigator,localStorage,Event:class{constructor(type){this.type=type}},setTimeout:cb=>{cb();return 0}});
  return {document,window,saved,status,faceLabel,speaker,accent,label,emit,clicks:()=>clicks,mic};
}
const settle=()=>new Promise(r=>setImmediate(r));

test('AURA abre con el cerebro avanzado listo, sin descarga ni toque extra',async()=>{
  const e=environment();
  await settle();
  assert.match(e.faceLabel.textContent,/Cerebro avanzado activo/);
  assert.equal(e.speaker.checked,true);
  assert.equal(e.accent.value,'es-AR');
  assert.equal(e.clicks(),0,'no se abre micrófono sin consentimiento previo');
});

test('AURA intenta reanudar escucha solo si hay permiso previo concedido',async()=>{
  const e=environment({consent:true,permission:'granted'});
  await settle();
  assert.equal(e.clicks(),1);
});

test('AURA no inicia micrófono automáticamente si el permiso no está concedido',async()=>{
  const e=environment({consent:true,permission:'prompt'});
  await settle();
  assert.equal(e.clicks(),0);
  assert.match(e.status.textContent,/lista/);
});

test('AURA no activa conversación sin sesión autorizada',async()=>{
  const e=environment({consent:true,authorized:false});
  await settle();
  assert.equal(e.clicks(),0);
  assert.match(e.status.textContent,/Conectá AURA/);
});

test('el servidor inyecta el arranque en la respuesta HTML',()=>{
  const server=readFileSync(new URL('./server.mjs',import.meta.url),'utf8');
  assert.ok(server.includes('aura-autostart-21.js?v=21'));
});
