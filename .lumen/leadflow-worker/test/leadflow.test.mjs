import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import worker from "../worker.mjs";
import {qualify} from "../core.mjs";

const sample={zona:"Zárate",presupuesto:600000,ambientes:2,urgencia:"este_mes"};
const post=(path,input)=>new Request("https://leadflow.example"+path,{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(input)});

test("priorities correspond to declared urgency",()=>{
  assert.equal(qualify(sample).prioridad,"media");
  assert.equal(qualify({...sample,urgencia:"esta_semana"}).prioridad,"alta");
  assert.equal(qualify({...sample,urgencia:"flexible"}).prioridad,"exploratoria");
});
test("invalid or inconsistent input is rejected",()=>{
  for(const data of [null,{}, {...sample,zona:""}, {...sample,presupuesto:1}, {...sample,presupuesto:NaN}, {...sample,ambientes:0}, {...sample,urgencia:"other"}]){
    assert.throws(()=>qualify(data));
  }
});
test("demo classifies without persisting or inventing inventory",async()=>{
  const response=await worker.fetch(post("/api/demo",sample),{});
  assert.equal(response.status,200);
  const value=await response.json();
  assert.equal(value.stored,false);
  assert.equal(value.resultado.prioridad,"media");
  assert.match(value.resultado.criterio,/solamente/);
});
test("bad payloads rejected",async()=>{
  const response=await worker.fetch(post("/api/demo",{...sample,ambientes:0}),{});
  assert.equal(response.status,400);
});
test("wrong media type rejected",async()=>{
  const response=await worker.fetch(new Request("https://leadflow.example/api/demo",{method:"POST",headers:{"content-type":"text/plain"},body:"hello"}),{});
  assert.equal(response.status,400);
});
test("real contacts are never accepted in demo mode",async()=>{
  const response=await worker.fetch(post("/api/leads",{email:"hello@example.com"}),{});
  assert.equal(response.status,503);
});
test("health does not claim leads or earnings",async()=>{
  const response=await worker.fetch(new Request("https://leadflow.example/health"),{});
  const data=await response.json();
  assert.equal(data.mode,"demo_only");
  assert.equal(data.real_leads,0);
  assert.equal(data.revenue,"not_verified");
});
test("static files are delegated to assets and no api fallback",async()=>{
  const env={ASSETS:{fetch:async()=>new Response("STATIC")}};
  const response=await worker.fetch(new Request("https://leadflow.example/"),env);
  assert.equal(await response.text(),"STATIC");
  const invalid=await worker.fetch(new Request("https://leadflow.example/api/unknown"),env);
  assert.equal(invalid.status,404);
});
test("oversized input is rejected",async()=>{
  const data={...sample,extra:"x".repeat(10000)};
  const response=await worker.fetch(post("/api/demo",data),{});
  assert.equal(response.status,400);
});

test("search button GET route returns a visible HTML result",async()=>{
  const query=new URLSearchParams(sample);
  const response=await worker.fetch(new Request("https://leadflow.example/buscar?"+query),{});
  assert.equal(response.status,200);
  assert.match(response.headers.get("content-type"),/text\/html/);
  const html=await response.text();
  assert.match(html,/Búsqueda analizada/);
  assert.match(html,/Prioridad de seguimiento/);
  assert.match(html,/media/i);
  assert.match(html,/no se buscaron propiedades reales/);
});
test("search route validates input and escapes HTML",async()=>{
  const params=new URLSearchParams({...sample,zona:"<script>alert(1)</script>"});
  const response=await worker.fetch(new Request("https://leadflow.example/buscar?"+params),{});
  const html=await response.text();
  assert.equal(response.status,200);
  assert.doesNotMatch(html,/<script>alert\(1\)<\/script>/);
  assert.match(html,/&lt;script&gt;/);
  const bad=await worker.fetch(new Request("https://leadflow.example/buscar?zona=Zarate"),{});
  assert.equal(bad.status,400);
  assert.match(await bad.text(),/Revisá tu búsqueda/);
});

test("landing includes working manual contact link and an explicit consent boundary",()=>{
  const html=readFileSync(new URL("../public/index.html",import.meta.url),"utf8");
  assert.match(html,/action="\/buscar"/);
  assert.match(html,/mailto:lumenstock2026@gmail\.com/);
  assert.match(html,/No envía nada automáticamente/);
  assert.doesNotMatch(html,/<script/);
});
test("search result contains a commercial next step",async()=>{
  const response=await worker.fetch(new Request("https://leadflow.example/buscar?"+new URLSearchParams(sample)),{});
  assert.equal(response.status,200);
  assert.match(await response.text(),/Solicitar propuesta/);
});
