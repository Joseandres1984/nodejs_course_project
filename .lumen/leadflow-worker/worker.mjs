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

function escapeHtml(v) {
  return String(v).replace(/[&<>"']/g, ch => ({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"
  })[ch]);
}
function page(body, status=200) {
  return new Response(body,{
    status,
    headers: {
      ...headers,
      "content-type":"text/html; charset=utf-8",
      "content-security-policy":"default-src 'none'; style-src 'self'; img-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
      "x-frame-options":"DENY"
    }
  });
}
function searchResults(params) {
  let result, error;
  try {
    result=qualify({
      zona:params.get("zona"),
      presupuesto:params.get("presupuesto"),
      ambientes:params.get("ambientes"),
      urgencia:params.get("urgencia")
    });
  } catch(err) {
    error=err instanceof InputError ? err.message : "No se pudo procesar la búsqueda.";
  }
  const rows=result ? [
    ["Prioridad de seguimiento",result.prioridad.toUpperCase()],
    ["Consulta recibida (simulación)",result.resumen],
    ["Siguiente acción",result.proximo_paso],
    ["Criterio",result.criterio]
  ] : [["Revisá los datos",error]];
  const cards=rows.map(row=>'<div class="result-item"><small>'+escapeHtml(row[0])+'</small><strong>'+escapeHtml(row[1])+'</strong></div>').join("");
  const html='<!doctype html><html lang="es"><head><meta charset="utf-8">'+
    '<meta name="viewport" content="width=device-width,initial-scale=1">'+
    '<title>Resultado · LUMEN LeadFlow AI</title><link rel="stylesheet" href="/style.css"></head>'+
    '<body><header class="shell top"><a class="brand" href="/">LUMEN <span>LEADFLOW AI</span></a>'+
    '<small class="chip">SIMULACIÓN SIN DATOS PERSONALES</small></header>'+
    '<main class="shell offer"><span class="eyebrow">RESULTADO DE LA DEMOSTRACIÓN</span>'+
    '<h1>'+ (result ? "Búsqueda analizada." : "Revisá tu búsqueda.") +'</h1>'+
    '<p>'+ (result ? "La consulta se clasificó correctamente para un seguimiento humano." : "No se pudo analizar porque faltan datos válidos.") +'</p>'+
    '<div class="panel">'+cards+'</div><p class="note">Esto es una demostración: no se buscaron propiedades reales ni se guardaron contactos.</p>'+
    '<a class="cta" href="/#demo">← Volver a probar</a> <a class="cta" href="mailto:lumenstock2026@gmail.com?subject=Consulta%20LUMEN%20LeadFlow%20AI&body=Hola%20equipo%20LUMEN%2C%0AQuiero%20informaci%C3%B3n%20sobre%20la%20implementaci%C3%B3n%20para%20mi%20inmobiliaria.">Solicitar propuesta →</a></main></body></html>';
  return page(html,error?400:200);
}

export default {
  async fetch(request,env={}) {
    const url=new URL(request.url);
    const path=url.pathname;
    if(path==="/buscar"&&request.method==="GET")return searchResults(url.searchParams);
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
