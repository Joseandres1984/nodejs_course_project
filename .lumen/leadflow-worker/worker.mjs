import { qualify, InputError } from "./core.mjs";
const headers = { "cache-control":"no-store", "x-content-type-options":"nosniff", "referrer-policy":"no-referrer" };
function json(data,status=200) { return Response.json(data,{status,headers}); }
async function readJson(request) {
  if (!(request.headers.get("content-type") || "").includes("application/json")) throw new InputError("Se requiere JSON.");
  const reader = request.body?.getReader();
  if (!reader) throw new InputError("Faltan datos.");
  const chunks=[];let size=0;
  for (;;) {
    const item=await reader.read();
    if (item.done) break;
    size+=item.value.byteLength;
    if (size>8192) { await reader.cancel();throw new InputError("Solicitud demasiado grande."); }
    chunks.push(item.value);
  }
  const bytes=new Uint8Array(size);let offset=0;
  for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
  try { return JSON.parse(new TextDecoder("utf-8",{fatal:true}).decode(bytes)); }
  catch { throw new InputError("JSON inválido."); }
}
export default {
  async fetch(request,env={}) {
    const path=new URL(request.url).pathname;
    if(path==="/health"&&request.method==="GET")return json({ok:true,service:"LUMEN LeadFlow AI",mode:"demo_only",real_leads:0,revenue:"not_verified"});
    if(path==="/api/demo"&&request.method==="POST"){
      try{return json({ok:true,demo:true,stored:false,resultado:qualify(await readJson(request))});}
      catch(error){return json({ok:false,error:error instanceof InputError?error.message:"No se pudo procesar."},400);}
    }
    if(path==="/api/leads")return json({ok:false,error:"Recepción de contactos reales no habilitada."},503);
    if(path.startsWith("/api/"))return json({ok:false,error:"Ruta desconocida."},404);
    if(!["GET","HEAD"].includes(request.method))return json({ok:false,error:"Método no permitido."},405);
    if(!env.ASSETS||typeof env.ASSETS.fetch!=="function")return json({ok:false,error:"Archivos estáticos no configurados."},503);
    return env.ASSETS.fetch(request);
  }
};
