import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext, Script} from 'node:vm';

const html=readFileSync(new URL('./index.html',import.meta.url),'utf8');
function part(begin,end){
  const a=html.indexOf(begin),b=html.indexOf(end,a+begin.length);
  assert.ok(a>=0&&b>a, 'Se encontró el circuito '+begin);
  return html.slice(a,b);
}
const sendCode=part('function send(text){','function watch(){');
const listenCode=part('function listen(){',"$('v9AutoTurn').addEventListener");
const stopCode=part('function stopSpeaking(){','function stopAll(){');

test('una nueva consulta reemplaza la espera anterior sin cerrar el diálogo',()=>{
  let cancelled=0,submitted=0;
  const els={
    v8Question:{textContent:''},
    v8Answer:{textContent:''},
    messageInput:{value:''},
    messageForm:{requestSubmit(){submitted++}}
  };
  const context={
    pending:true,asking:true,assistantBaseline:0,voiceWaitTimer:null,
    $:id=>els[id],document:{querySelectorAll:()=>[]},
    window:{AuraChatControl:{isBusy:()=>true,cancel:()=>{cancelled++;context.asking=false;}}},
    stopListening(){},stopSpeaking(){},setPhase(){},
    clearVoiceTimer(){},
    setTimeout(){return 1}
  };
  runInNewContext(sendCode+';send("¿Qué hora es?")',context);
  assert.equal(cancelled,1);
  assert.equal(submitted,1);
  assert.equal(context.pending,true);
  assert.equal(els.v8Question.textContent,'¿Qué hora es?');
  assert.equal(els.messageInput.value,'¿Qué hora es?');
});

test('tocar el micrófono durante una respuesta cancela y permite escuchar',()=>{
  let cancelled=0,started=0;
  function Rec(){this.start=()=>started++}
  const context={
    open:true,pending:true,autoTurn:true,
    autoTimer:null,Rec,recognizer:null,recognized:false,
    $:id=>id==='accent'?{value:'es-AR'}:{},
    window:{AuraChatControl:{isBusy:()=>true,cancel:()=>cancelled++}},
    document:{hidden:false},clearVoiceTimer(){},clearTimeout(){},
    stopListening(){},stopSpeaking(){},setPhase(){},
    scheduleSilenceRetry(){return false},send(){},
  };
  runInNewContext(listenCode+';listen()',context);
  assert.equal(cancelled,1);
  assert.equal(started,1);
  assert.equal(context.pending,false);
  assert.equal(context.recognizer?.lang,'es-AR');
});

test('detener audio invalida el turno antes del callback de Safari',()=>{
  let observedToken=null;
  const context={
    utterance:{id:99},speaking:true,voiceWatchdog:null,
    clearTimeout(){},
    window:{AuraVoice:{stop(){observedToken=context.utterance}}},
    stopLips(){}
  };
  runInNewContext(stopCode+';stopSpeaking()',context);
  assert.equal(observedToken,null);
  assert.equal(context.speaking,false);
  assert.equal(context.utterance,null);
});

test('se recupera un único silencio y la animación de boca se detiene al cortar voz',()=>{
  assert.ok(html.includes("e.error==='no-speech'&&scheduleSilenceRetry()"));
  assert.ok(html.includes('silenceRetry>=1'));
  assert.ok(html.includes('silenceRetry=0;try{r.stop?.()}'));
  assert.ok(html.includes('stopSpeaking();\n    setPhase(\'error\',\'El iPhone no inició el audio.'));
  const rig=readFileSync(new URL('./aura-presence-23.js',import.meta.url),'utf8');
  assert.ok(rig.includes("if(phase==='listening')return"));
  assert.ok(rig.includes("rigPhase!=='ready'"));
  assert.ok(rig.includes("rigPhase==='ready')scheduleRig()"));
});

test('los scripts embebidos de la página siguen siendo sintácticamente válidos',()=>{
  const scripts=[...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)]
    .map(x=>x[1]).filter(x=>x.trim());
  assert.ok(scripts.length>2);
  for(const script of scripts)new Script(script);
});
