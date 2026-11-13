import {timingSafeEqual,randomBytes,createHmac} from 'node:crypto';
import {generateWithFallback} from './aura-resilience.mjs';

const requests=new Map();
const failedLogins=new Map();
const SESSION_SECONDS=30*24*60*60;
const COOKIE='aura_session';
function sessionKey(){return process.env.AURA_SESSION_SECRET||process.env.AURA_ACCESS_CODE||'';}
function signature(data){return createHmac('sha256',sessionKey()).update(data).digest('base64url');}
function newSession(){
  const payload='v1.'+Math.floor(Date.now()/1000+SESSION_SECONDS)+'.'+randomBytes(24).toString('base64url');
  return payload+'.'+signature(payload);
}
function validSession(req){
  const raw=String(req.headers.cookie||'').split(';').map(x=>x.trim()).find(x=>x.startsWith(COOKIE+'='));
  const token=raw?.slice(COOKIE.length+1)||'';
  if(!/^v1\\.\\d{10,11}\\.[a-zA-Z0-9_-]{32}\\.[a-zA-Z0-9_-]{43}$/.test(token)||!sessionKey())return false;
  const parts=token.split('.'),expires=Number(parts[1]),now=Math.floor(Date.now()/1000);
  if(expires<=now||expires>now+SESSION_SECONDS+60)return false;
  return equals(parts[3],signature(parts.slice(0,3).join('.')));
}
function cookieOptions(req,clear=false){
  const secure=req.socket.encrypted||String(req.headers['x-forwarded-proto']||'').split(',')[0].trim()==='https';
  return COOKIE+'='+ (clear?'':newSession())+'; Path=/api/aura; HttpOnly; SameSite=Strict; '+(clear?'Max-Age=0':'Max-Age='+SESSION_SECONDS)+(secure?'; Secure':'');
}
function sameOrigin(req){
  const origin=req.headers.origin;
  if(!origin)return true;
  try{return new URL(origin).host===req.headers.host;}catch{return false;}
}
function loginAllowed(ip){
  const now=Date.now(),x=failedLogins.get(ip)||{since:now,tries:0};
  if(now-x.since>15*60*1000){x.since=now;x.tries=0;}
  x.tries++;failedLogins.set(ip,x);
  if(failedLogins.size>2048)for(const [key,val] of failedLogins){if(now-val.since>15*60*1000)failedLogins.delete(key);}
  return x.tries<=8;
}
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
    send(res,200,{advancedConfigured:enabled,localAvailable:true,sessionActive:enabled&&validSession(req)});
    return true;
  }
  if(req.method==='POST'&&!sameOrigin(req)){send(res,403,{error:'Origen no autorizado'});return true;}
  if(url.pathname==='/api/aura/login'&&req.method==='POST'){
    if(!enabled){send(res,503,{error:'La conexión avanzada todavía no está configurada.'});return true;}
    const ip=String(req.socket.remoteAddress||'').slice(0,100);
    if(!loginAllowed(ip)){send(res,429,{error:'Demasiados intentos. Probá de nuevo dentro de 15 minutos.'});return true;}
    let submitted='';
    try{submitted=String((await readJSON(req)).code||'').slice(0,200);}catch{send(res,400,{error:'Solicitud inválida'});return true;}
    if(!equals(submitted,process.env.AURA_ACCESS_CODE)){send(res,401,{error:'El código privado no coincide.'});return true;}
    failedLogins.delete(ip);
    res.setHeader('Set-Cookie',cookieOptions(req));
    send(res,200,{sessionActive:true,expiresInDays:30});
    return true;
  }
  if(url.pathname==='/api/aura/logout'&&req.method==='POST'){
    res.setHeader('Set-Cookie',cookieOptions(req,true));
    send(res,200,{sessionActive:false});
    return true;
  }
  if(url.pathname!=='/api/aura/chat'||req.method!=='POST'){send(res,404,{error:'No encontrado'});return true;}
  if(!enabled){send(res,503,{error:'El cerebro avanzado todavía no está conectado. Se necesita una clave del proveedor y una contraseña privada en el servidor.'});return true;}
  if(!validSession(req)){send(res,401,{error:'Necesitás conectar AURA una sola vez para usar el cerebro avanzado.'});return true;}
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
