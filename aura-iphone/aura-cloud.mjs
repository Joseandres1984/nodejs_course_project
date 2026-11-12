import {timingSafeEqual} from 'node:crypto';

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
    if(bytes>16384)throw Error('Solicitud demasiado grande');
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
    const personality=String(body.personality||'Cálida y profesional').slice(0,70);
    const safeModel=/^gemini-[\w.-]{4,90}$/.test(process.env.GEMINI_MODEL||'')?process.env.GEMINI_MODEL:'gemini-3.5-flash-lite';
    const content={
      systemInstruction:{parts:[{text:'Sos AURA, un asistente personal. Respondé siempre en español argentino claro, con voseo. Priorizá utilidad, pertinencia y precisión. No inventes accesos, acciones realizadas ni datos. Sé breve salvo que el usuario pida detalles. Personalidad: '+personality}]},
      contents:messages,
      generationConfig:{temperature:.45,maxOutputTokens:650}
    };
    const out=await fetch('https://generativelanguage.googleapis.com/v1beta/models/'+encodeURIComponent(safeModel)+':generateContent',{
      method:'POST',headers:{'Content-Type':'application/json','x-goog-api-key':process.env.GEMINI_API_KEY},
      body:JSON.stringify(content),signal:AbortSignal.timeout(20000)
    });
    if(!out.ok){send(res,502,{error:out.status===429?'El proveedor llegó a su límite gratuito. Probá después.':out.status===404?'El modelo no está disponible en este proyecto. Hay que seleccionar uno habilitado.':'El proveedor de IA no pudo responder (código '+out.status+').'});return true;}
    const json=await out.json(),answer=(json.candidates?.[0]?.content?.parts||[]).map(p=>p.text||'').join('').trim();
    if(!answer){send(res,502,{error:'La IA no devolvió una respuesta de texto.'});return true;}
    send(res,200,{answer:answer.slice(0,4000),engine:'cloud'});
  }catch(e){
    const invalid=/JSON|grande/.test(String(e?.message))||e instanceof SyntaxError;
    send(res,invalid?400:502,{error:invalid?'Solicitud inválida':e?.name==='TimeoutError'?'La IA tardó demasiado en responder':'No se pudo completar la consulta.'});
  }
  return true;
}
