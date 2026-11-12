import {timingSafeEqual} from 'node:crypto';
import {generateWithFallback} from './aura-resilience.mjs';

const requests=new Map();
function send(res,status,data){
  res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'});
  res.end(JSON.stringify(data));
}
function equals(a,b){
  const x=Buffer.from(String(a||'')),y=Buffer.from(String(b||''));
  return x.length===y.length&&timingSafeEqual(x,y);
}
async function readJSON(req){
  let bytes=0, chunks=[];
  for await(const chunk of req){
    bytes+=chunk.length;
    if(bytes>5*1024*1024)throw Error('Solicitud demasiado grande');
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}
const quota=ip=>{
  const now=Date.now(),x=requests.get(ip)||{minute:now,day:now,min:0,total:0};
  if(now-x.minute>60000){x.minute=now;x.min=0;}
  if(now-x.day>86400000){x.day=now;x.total=0;}
  x.min++;x.total++;requests.set(ip,x);
  if(requests.size>2048){for(const [k,v] of requests){if(now-v.day>86400000)requests.delete(k);}}
  return x.min<=6&&x.total<=80;
};
export async function handleAuraAPI(req,res,url){
  if(!url.pathname.startsWith('/api/aura/'))return false;
  const enabled=!!(process.env.GEMINI_API_KEY&&process.env.AURA_ACCESS_CODE);
  if(url.pathname==='/api/aura/status'&&req.method==='GET'){
    send(res,200,{advancedConfigured:enabled,localAvailable:true});
    return true;
  }
  if(url.pathname!=='/api/aura/chat'||req.method!=='POST'){send(res,404,{error:'No encontrado'});return true;}
  if(!enabled){send(res,503,{error:'El cerebro avanzado todavía no está conectado. Se necesita una clave del proveedor y una contraseña privada en el servidor.'});return true;}
  const origin=req.headers.origin;
  if(origin){try{if(new URL(origin).host!==req.headers.host){send(res,403,{error:'Origen no autorizado'});return true;}}catch{send(res,403,{error:'Origen no autorizado'});return true;}}
  if(!equals(req.headers['x-aura-code'],process.env.AURA_ACCESS_CODE)){send(res,401,{error:'Código privado incorrecto'});return true;}
  const ip=String(req.socket.remoteAddress||'').slice(0,100);
  if(!quota(ip)){send(res,429,{error:'Alcanzaste el límite de solicitudes de este prototipo.'});return true;}
  try{
    const body=await readJSON(req);
    const raw=Array.isArray(body.messages)?body.messages:[];
    const messages=raw.filter(x=>x&&['user','assistant'].includes(x.role)&&typeof x.text==='string')
      .slice(-10).map(x=>({role:x.role==='assistant'?'model':'user',parts:[{text:x.text.slice(0,1600)}]}));
    if(!messages.length||messages.at(-1).role!=='user'){send(res,400,{error:'Falta la consulta del usuario'});return true;}
    // Foto enviada explícitamente: validamos formato, firma y tamaño; no la almacenamos.
    if(body.image!==undefined){
      const image=body.image;
      const allowed=['image/jpeg','image/png','image/webp'];
      const data=image && typeof image.data==='string' ? image.data : '';
      const mime=image && typeof image.mimeType==='string' ? image.mimeType : '';
      if(!allowed.includes(mime)||data.length<100||data.length>4.3*1024*1024
        ||data.length%4!==0||!/^[A-Za-z0-9+/]*={0,2}$/.test(data)){
        send(res,400,{error:'La imagen no es válida o es demasiado grande (máximo 3 MB).'});return true;
      }
      const binary=Buffer.from(data,'base64');
      const jpeg=binary[0]===0xff&&binary[1]===0xd8&&binary[2]===0xff;
      const png=binary.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10]));
      const webp=binary.subarray(0,4).toString('ascii')==='RIFF'&&binary.subarray(8,12).toString('ascii')==='WEBP';
      if(binary.length>3*1024*1024||binary.length<80
        ||!((mime==='image/jpeg'&&jpeg)||(mime==='image/png'&&png)||(mime==='image/webp'&&webp))){
        send(res,400,{error:'La foto no coincide con un formato de imagen admitido.'});return true;
      }
      messages[messages.length-1].parts.push({inlineData:{mimeType:mime,data}});
    }
    const personality=String(body.personality||'Cálida y profesional').slice(0,70);
    const safeModel=/^gemini-[\w.-]{4,90}$/.test(process.env.GEMINI_MODEL||'')?process.env.GEMINI_MODEL:'gemini-3.5-flash-lite';
    const content={
      systemInstruction:{parts:[{text:'Sos AURA, un asistente personal. Respondé siempre en español argentino claro, con voseo. Priorizá utilidad, pertinencia y precisión. No inventes accesos, acciones realizadas ni datos. Sé breve salvo que el usuario pida detalles. Personalidad: '+personality}]},
      contents:messages,
      generationConfig:{maxOutputTokens:2048,thinkingConfig:{thinkingLevel:'low'}}
    };
    const result=await generateWithFallback({
      key:process.env.GEMINI_API_KEY,model:safeModel,
      fallbackModel:process.env.GEMINI_FALLBACK_MODEL||'gemini-3.5-flash-lite',
      content
    });
    if(!result.ok){
      const messages={
        quota:'Google alcanzó el límite de consultas del proyecto. Probá más tarde; no vamos a insistir para evitar exceder la cuota.',
        unavailable:'Google está temporalmente saturado. AURA ya reintentó y probó el modelo alternativo. Volvé a intentarlo dentro de un minuto.',
        credentials:'La clave de Google fue rechazada. Revisá la configuración privada de Render.',
        request:'Google rechazó la solicitud. Revisaremos la configuración del modelo.',
        empty:'Google no devolvió una respuesta de texto. Probá reformular la pregunta.',
        provider:'Google no pudo procesar la consulta.'
      };
      console.warn('AURA_PROVIDER',{reason:result.reason,code:result.providerStatus||result.status,model:result.model});
      send(res,result.status,{error:messages[result.reason]||messages.provider,retryable:result.reason==='unavailable'});
      return true;
    }
    const answer=result.answer;
    if(/(?:^|\n)\s*(?:yes,|no fake facts|reasoning|thinking|internal plan|system instruction|analysis:)/i.test(answer)||/^\s*(?:hello|i am|we should)\b/i.test(answer)){
      send(res,502,{error:'La IA generó una respuesta que no pasó el control de calidad. Probá de nuevo.'});return true;
    }
    send(res,200,{answer:answer.slice(0,4000),engine:'cloud',model:result.model,fallbackUsed:result.fallback});
  }catch(e){
    const invalid=/JSON|grande/.test(String(e?.message))||e instanceof SyntaxError;
    send(res,invalid?400:502,{error:invalid?'Solicitud inválida':e?.name==='TimeoutError'?'La IA tardó demasiado en responder':'No se pudo completar la consulta.'});
  }
  return true;
}
