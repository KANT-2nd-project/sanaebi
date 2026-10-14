import { test } from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import { once } from "node:events";
import { proxyChat } from "../scripts/chat-proxy.mjs";

async function listen(server) { server.listen(0, "127.0.0.1"); await once(server, "listening"); return server.address().port; }
async function close(server) { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
test("Gradio prefix preserves POST, status, JSON and no-store; redirects retain query", async () => {
 let calls = 0;
 const backend = http.createServer((req, res) => {
  calls++; assert.equal(req.url, "/chat/gradio_api/test?x=1");
  let body = ""; req.on("data", chunk => body += chunk); req.on("end", () => {
   assert.equal(body, '{"question":"휴가"}');
   res.writeHead(502, { "content-type":"application/json", "cache-control":"public", expires:"tomorrow" }); res.end('{"reason":"실패"}');
  });
 });
 const port = await listen(backend);
 const proxy = http.createServer((req,res) => { if (!proxyChat(req,res,{port})) {res.writeHead(404); res.end();} });
 const front = await listen(proxy);
 try {
  const redirected = await fetch(`http://127.0.0.1:${front}/chat?q=1`,{redirect:"manual"});
  assert.equal(redirected.status,308); assert.equal(redirected.headers.get("location"),"/chat/?q=1");
  const r = await fetch(`http://127.0.0.1:${front}/chat/gradio_api/test?x=1`,{method:"POST",body:JSON.stringify({question:"휴가"})});
  assert.equal(r.status,502); assert.deepEqual(await r.json(),{reason:"실패"});
  assert.equal(r.headers.get("cache-control"),"no-store"); assert.equal(r.headers.get("expires"),null);
  assert.match(r.headers.get("x-robots-tag"),/noindex/); assert.equal(calls,1);
 } finally { await close(proxy); await close(backend); }
});
test("delayed upstream produces 504 without retry; refused connection produces 502", async () => {
 let calls=0;
 const backend = http.createServer(() => { calls++; });
 const port=await listen(backend);
 const proxy=http.createServer((req,res)=>proxyChat(req,res,{port,readMs:25}));
 const front=await listen(proxy);
 try {
  const r=await fetch(`http://127.0.0.1:${front}/chat/`); assert.equal(r.status,504); assert.equal(calls,1);
  await close(backend);
  const failed=await fetch(`http://127.0.0.1:${front}/chat/`); assert.equal(failed.status,502); assert.equal(failed.headers.get("cache-control"),"no-store");
 } finally { await close(proxy); if(backend.listening) await close(backend); }
});
test("SSE is delivered before upstream finishes", async () => {
 const backend=http.createServer((req,res)=>{res.writeHead(200,{"content-type":"text/event-stream"});res.write("data: first\n\n");});
 const port=await listen(backend);
 const proxy=http.createServer((req,res)=>proxyChat(req,res,{port}));
 const front=await listen(proxy);
 try {
  const r=await fetch(`http://127.0.0.1:${front}/chat/events`);
  const reader=r.body.getReader(); const {value}=await reader.read(); assert.match(new TextDecoder().decode(value),/data: first/); await reader.cancel();
 } finally {await close(proxy);await close(backend);}
});
test("reused upstream sockets do not accumulate connect listeners", async () => {
 const warnings=[];const onWarning=w=>{if(w.name==='MaxListenersExceededWarning')warnings.push(w);};
 process.on('warning',onWarning);
 const backend=http.createServer((req,res)=>res.end('ok'));
 const port=await listen(backend);const proxy=http.createServer((req,res)=>proxyChat(req,res,{port}));const front=await listen(proxy);
 try {
  for(let i=0;i<24;i++){const r=await fetch(`http://127.0.0.1:${front}/chat/`);await r.text();}
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(warnings.length,0,'upstream keep-alive must not leak connect listeners');
 } finally {process.off('warning',onWarning);await close(proxy);await close(backend);}
});
