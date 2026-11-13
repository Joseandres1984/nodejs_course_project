import test from 'node:test';
import assert from 'node:assert/strict';
import {Readable} from 'node:stream';
import {handleAuraAPI} from './aura-cloud.mjs';

process.env.GEMINI_API_KEY='test-key-not-real';
process.env.AURA_ACCESS_CODE='test-password-not-real';
process.env.AURA_SESSION_SECRET='test-cookie-key-not-real';

async function request(method,path,options={}){
  const req=Readable.from(options.body===undefined?[]:[Buffer.from(JSON.stringify(options.body))]);
  req.method=method;
  req.headers={host:'aura.example.test',origin:'https://aura.example.test',...(options.headers||{})};
  req.socket={remoteAddress:options.ip||'127.0.0.1',encrypted:false};
  const res={
    statusCode:0,headers:{},body:'',
    setHeader(name,value){this.headers[name.toLowerCase()]=value;},
    writeHead(code,headers){this.statusCode=code;for(const [k,v] of Object.entries(headers))this.headers[k.toLowerCase()]=v;},
    end(value=''){this.body=String(value);}
  };
  const handled=await handleAuraAPI(req,res,new URL(path,'https://aura.example.test'));
  assert.equal(handled,true);
  return {...res,json:JSON.parse(res.body)};
}

test('AURA: requiere código una sola vez y emite cookie HttpOnly',async()=>{
  const initial=await request('GET','/api/aura/status');
  assert.equal(initial.statusCode,200);
  assert.equal(initial.json.sessionActive,false);
  const wrong=await request('POST','/api/aura/login',{body:{code:'incorrecto'}});
  assert.equal(wrong.statusCode,401);
  const success=await request('POST','/api/aura/login',{body:{code:process.env.AURA_ACCESS_CODE}});
  assert.equal(success.statusCode,200);
  assert.equal(success.json.sessionActive,true);
  const cookie=success.headers['set-cookie'];
  assert.match(cookie,/^aura_session=v1\./);
  assert.match(cookie,/HttpOnly/);
  assert.match(cookie,/SameSite=Strict/);
  assert.match(cookie,/Max-Age=2592000/);
  assert.doesNotMatch(cookie,/test-password-not-real/);
  const reopened=await request('GET','/api/aura/status',{headers:{cookie:cookie.split(';')[0]}});
  assert.equal(reopened.json.sessionActive,true);
  const expired=await request('GET','/api/aura/status',{headers:{cookie:'aura_session=v1.1234567890.invalid.invalid'}});
  assert.equal(expired.json.sessionActive,false);
});

test('AURA: no permite chat sin sesión y rechaza origen externo',async()=>{
  const denied=await request('POST','/api/aura/chat',{body:{messages:[{role:'user',text:'Hola'}]}});
  assert.equal(denied.statusCode,401);
  const external=await request('POST','/api/aura/login',{headers:{origin:'https://otro.example.test'},body:{code:process.env.AURA_ACCESS_CODE}});
  assert.equal(external.statusCode,403);
});

test('AURA: cerrar sesión elimina la cookie',async()=>{
  const res=await request('POST','/api/aura/logout');
  assert.equal(res.statusCode,200);
  assert.match(res.headers['set-cookie'],/Max-Age=0/);
  assert.equal(res.json.sessionActive,false);
});
