/* Smoke test: solo si AURA_RUN_DIAGNOSTIC = 1. Nunca imprime la API key. */
export async function runAuraDiagnostic(){
 if(process.env.AURA_RUN_DIAGNOSTIC!=='1')return;
 const key=process.env.GEMINI_API_KEY||'', model=process.env.GEMINI_MODEL||'gemini-3.5-flash';
 if(!key){console.info("AURA_DIAG "+JSON.stringify({configured:false,reason:'GEMINI_API_KEY ausente'}));return;}
 const prompts=[
   'Presentate en dos frases, en español argentino. Sos una IA llamada AURA.',
   'Dame tres ideas concretas de negocio digital para empezar con poco dinero. Respondé en español argentino.'
 ];
 for(let i=0;i<prompts.length;i++){
   try{
    const result=await fetch('https://generativelanguage.googleapis.com/v1beta/models/'+encodeURIComponent(model)+':generateContent',{
      method:'POST',
      headers:{'Content-Type':'application/json','x-goog-api-key':key},
      body:JSON.stringify({
        systemInstruction:{parts:[{text:'Sos AURA. Respondé con precisión en español argentino. No inventes hechos ni acciones.'}]},
        contents:[{role:'user',parts:[{text:prompts[i]}]}],
        generationConfig:{maxOutputTokens:2048,thinkingConfig:{thinkingLevel:'low'}}
      }),
      signal:AbortSignal.timeout(18000)
    });
    const payload=await result.json();
    const answer=(payload.candidates?.[0]?.content?.parts||[]).filter(p=>!p.thought).map(p=>p.text||'').join('').trim();
    const err=payload.error?.message||null;
    console.info("AURA_DIAG "+JSON.stringify({
       index:i+1,model,http_status:result.status,
       valid_answer:result.ok && answer.length>30 && /[áéíóúñ]|soy|podés|negocio|servicio|plantillas/i.test(answer) && !/^\s*(yes|no fake facts|analysis|thinking)/i.test(answer),
       answer_preview:answer.slice(0,450),
       failure:!result.ok ? String(err||'API error').slice(0,180):!answer?'No se recibió texto':null
    }));
   }catch(e){console.info("AURA_DIAG "+JSON.stringify({index:i+1,model,error:String(e?.message||e).slice(0,160)}));}
 }
}