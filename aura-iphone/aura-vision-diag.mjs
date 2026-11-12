import {generateWithFallback} from './aura-resilience.mjs';

// Prueba consentida de imagen sintética (cuadrado rojo 16x16), nunca usa fotos reales.
export async function runVisionDiagnostic(){
 if(process.env.AURA_VISION_DIAG!=='1')return;
 if(!process.env.GEMINI_API_KEY){
  console.info('AURA_VISION_DIAG '+JSON.stringify({configured:false}));return;
 }
 const img='iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAGUlEQVR4nGP8ICfHQApgIkn1qIZRDUNKAwDJdwFMpmpOGwAAAABJRU5ErkJggg==';
 const prompt='¿Qué color predomina en esta imagen? Respondé en una oración breve en español.';
 const data={
  systemInstruction:{parts:[{text:'Sos AURA, respondé en español argentino. No inventes nada fuera de la imagen.'}]},
  contents:[{role:'user',parts:[{text:prompt},{inlineData:{mimeType:'image/png',data:img}}]}],
  generationConfig:{maxOutputTokens:256,thinkingConfig:{thinkingLevel:'low'}}
 };
 try{
  const result=await generateWithFallback({
    key:process.env.GEMINI_API_KEY,model:process.env.GEMINI_MODEL||'gemini-3.5-flash',
    fallbackModel:process.env.GEMINI_FALLBACK_MODEL||'gemini-3.5-flash-lite',content:data,timeoutMs:18000
  });
  const answer=String(result.answer||'').slice(0,180);
  console.info('AURA_VISION_DIAG '+JSON.stringify({
    model:result.model,providerStatus:result.providerStatus||result.status,
    imageRecognized:result.ok&&/rojo|rojizo|red/i.test(answer),
    text:answer,result:result.ok?'ok':result.reason
  }));
 }catch(e){console.info('AURA_VISION_DIAG '+JSON.stringify({result:'error',message:String(e?.message||e).slice(0,110)}));}
}