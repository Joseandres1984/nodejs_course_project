import {createServer} from "node:http";
import {readFile,stat} from "node:fs/promises";
import {fileURLToPath} from "node:url";
import {resolve,extname,sep} from "node:path";
const root=resolve(fileURLToPath(new URL(".",import.meta.url)));
const port=Number(process.env.PORT||3000);
const mime={".html":"text/html; charset=utf-8",".webmanifest":"application/manifest+json; charset=utf-8",".js":"text/javascript; charset=utf-8",".svg":"image/svg+xml"};
createServer(async(req,res)=>{
try{
  const url=new URL(req.url,"http://localhost");
  if(url.pathname==="/healthz"){res.writeHead(200,{"Content-Type":"text/plain"});res.end("ok");return;}
  const rel=url.pathname==="/"?"/index.html":url.pathname;
  const file=resolve(root,"."+decodeURIComponent(rel));
  if(!file.startsWith(root+sep))throw Error("invalid path");
  if(!(await stat(file)).isFile())throw Error("missing");
  const bytes=await readFile(file);
  res.writeHead(200,{"Content-Type":mime[extname(file)]||"application/octet-stream","X-Content-Type-Options":"nosniff","Referrer-Policy":"no-referrer","Cache-Control":extname(file)===".html"?"no-store":"public,max-age=300"});
  res.end(bytes);
}catch{res.writeHead(404,{"Content-Type":"text/plain"});res.end("Not found");}
}).listen(port,"0.0.0.0",()=>console.log("AURA iPhone listening "+port));
