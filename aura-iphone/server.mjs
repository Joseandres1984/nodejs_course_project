import {createServer} from "node:http";
import {handleAuraAPI} from './aura-cloud.mjs';
import {runAuraDiagnostic} from './aura-diagnostic.mjs';
import {runVisionDiagnostic} from './aura-vision-diag.mjs';
import {readFile,stat} from "node:fs/promises";
import {fileURLToPath} from "node:url";
import {resolve,extname,sep} from "node:path";
const root=resolve(fileURLToPath(new URL(".",import.meta.url)));
const port=Number(process.env.PORT||3000);
const mime={".html":"text/html; charset=utf-8",".webmanifest":"application/manifest+json; charset=utf-8",".js":"text/javascript; charset=utf-8",".glb":"model/gltf-binary",".webp":"image/webp",".bin":"application/octet-stream",".svg":"image/svg+xml"};
createServer(async(req,res)=>{
try{
  const url=new URL(req.url,"http://localhost");
  if(await handleAuraAPI(req,res,url))return;
  if(url.pathname==="/healthz"){res.writeHead(200,{"Content-Type":"text/plain"});res.end("ok");return;}
  const rel=url.pathname==="/"?"/index.html":url.pathname;
  const file=resolve(root,"."+decodeURIComponent(rel));
  if(!file.startsWith(root+sep))throw Error("invalid path");
  if(!(await stat(file)).isFile())throw Error("missing");
  let bytes=await readFile(file);
  // Hotfix de conversación antes de cargar el estado guardado de Safari.
  if(file===resolve(root,"index.html")){
    const patch=await readFile(resolve(root,"aura-fix-12.js"),"utf8");
    bytes=Buffer.from(bytes.toString("utf8").replace('src="./aura-brain-13.js"','src="./aura-brain-13.js?v=22"').replace("</head>","<script>"+patch+"</script><script defer src=\"./aura-neural-lab-15.js?v=15\"></script><script defer src=\"./aura-vision-16.js?v=16\"></script><script defer src=\"./aura-jarvis-17.js?v=17\"></script><script defer src=\"./aura-autostart-21.js?v=26\"></script><script defer src=\"./aura-presence-23.js?v=26\"></script><script type=\"module\" src=\"./aura-3d.bundle.js?v=35\"></script></head>"));
  }
  res.writeHead(200,{"Content-Type":mime[extname(file)]||"application/octet-stream","X-Content-Type-Options":"nosniff","Referrer-Policy":"no-referrer","Cache-Control":extname(file)===".html"?"no-store":"public,max-age=300"});
  res.end(bytes);
}catch{res.writeHead(404,{"Content-Type":"text/plain"});res.end("Not found");}
}).listen(port,"0.0.0.0",()=>(console.log("AURA iPhone listening "+port),runAuraDiagnostic().catch(e=>console.error("AURA_DIAG fatal",e.message)),runVisionDiagnostic().catch(e=>console.error("AURA_VISION_DIAG fatal",e.message))));
