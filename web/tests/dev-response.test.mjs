import { test } from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { once } from "node:events";
import { applyApiNoStore } from "../scripts/dev-response.mjs";

for (const mode of ["implicit", "object", "raw"]) {
  test(`개발 API는 ${mode} 응답의 상태·본문을 유지하고 캐시를 금지한다`, async () => {
    const server = createServer((req, res) => {
      applyApiNoStore(res);
      res.setHeader("Cache-Control", "public, max-age=3600");
      res.setHeader("Expires", "Wed, 14 Oct 2037 00:00:00 GMT");
      if (mode === "implicit") res.statusCode = 500;
      if (mode === "object") res.writeHead(502, { "Cache-Control": "public", "Content-Type": "application/json" });
      if (mode === "raw") res.writeHead(422, "Unprocessable Entity", ["cache-control", "public", "Expires", "future", "Content-Type", "application/json"]);
      res.end('{"ok":false,"reason":"test"}');
    });
    server.listen(0, "127.0.0.1"); await once(server, "listening");
    try {
      const response = await fetch(`http://127.0.0.1:${server.address().port}/api/ask`);
      assert.equal(response.status, { implicit: 500, object: 502, raw: 422 }[mode]);
      assert.equal(response.headers.get("cache-control"), "no-store");
      assert.equal(response.headers.get("expires"), null);
      assert.deepEqual(await response.json(), { ok: false, reason: "test" });
    } finally { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
  });
}
