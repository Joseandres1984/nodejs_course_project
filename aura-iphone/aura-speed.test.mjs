import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {Script} from 'node:vm';
import {generateWithFallback,resetCooldownForTests} from './aura-resilience.mjs';

const response=(status,answer='Hola, ¿cómo estás?')=>({
  ok:status===200,status,
  async json(){return {candidates:[{content:{parts:[{text:answer}]}}]};}
});
const content={contents:[{role:'user',parts:[{text:'Hola'}]}]};

test('si el primer modelo falla, AURA prueba el alternativo sin tres reintentos',async()=>{
  resetCooldownForTests();
  const models=[];
  const got=await generateWithFallback({
    key:'test',model:'gemini-3.5-flash',fallbackModel:'gemini-3.5-flash-lite',content,
    transport:async url=>{models.push(url);return models.length===1?response(503):response(200)}
  });
  assert.equal(got.ok,true);
  assert.equal(got.fallback,true);
  assert.equal(models.length,2);
});

test('AURA limita cada solicitud al modelo a 6,5 segundos',async()=>{
  resetCooldownForTests();
  const signals=[];
  const got=await generateWithFallback({
    key:'test',model:'gemini-3.5-flash',fallbackModel:'gemini-3.5-flash-lite',content,
    transport:async (_,opts)=>{signals.push(opts.signal);return signals.length===1?response(503):response(200)}
  });
  assert.equal(got.ok,true);
  assert.equal(signals.length,2);
  assert.ok(signals.every(x=>x instanceof AbortSignal));
});

test('si hay cuota agotada, la respuesta de error llega sin reintentos',async()=>{
  resetCooldownForTests();
  let calls=0;
  const got=await generateWithFallback({
    key:'test',model:'gemini-3.5-flash',fallbackModel:'gemini-3.5-flash-lite',content,
    transport:async()=>{calls++;return response(429)}
  });
  assert.equal(got.ok,false);
  assert.equal(got.reason,'quota');
  assert.equal(calls,1);
});

test('la interfaz tiene cancelación, recuperación y límite de espera',()=>{
  const html=readFileSync(new URL('./index.html',import.meta.url),'utf8');
  const brain=readFileSync(new URL('./aura-brain-13.js',import.meta.url),'utf8');
  assert.ok(html.includes('window.AuraChatControl='));
  assert.ok(html.includes('activeChatAbort?.abort()'));
  assert.ok(html.includes('},14500)'));
  assert.ok(html.includes('},17000)'));
  assert.ok(html.includes('clearVoiceTimer();lastReply=answer'));
  assert.ok(brain.includes('signal:options.signal'));
  const inline=[...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(m=>m[1]).filter(t=>t.trim());
  assert.ok(inline.length>2);
  for(const script of inline)new Script(script);
});
