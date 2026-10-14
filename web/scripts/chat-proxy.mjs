import http from "node:http";
import { applyApiNoStore } from "./dev-response.mjs";

/** Streaming Gradio prefix; API rewrites and HMR remain owned by Next. */
export function proxyChat(request, response, { port = 8000, connectMs = 5000, readMs = 60000 } = {}) {
  const pathname = (request.url || "/").split("?")[0];
  if (pathname !== "/chat" && !pathname.startsWith("/chat/")) return false;
  applyApiNoStore(response);
  response.setHeader("X-Robots-Tag", "noindex, nofollow");
  if (pathname === "/chat") {
    const query = request.url.includes("?") ? request.url.slice(request.url.indexOf("?")) : "";
    response.writeHead(308, { Location: `/chat/${query}` });
    response.end();
    return true;
  }
  const headers = { ...request.headers,
    host: request.headers.host,
    "x-forwarded-host": request.headers.host,
    "x-forwarded-proto": "http",
    "x-forwarded-for": request.socket.remoteAddress,
  };
  delete headers.connection;
  const upstream = http.request({ hostname: "127.0.0.1", port, path: request.url, method: request.method, headers });
  function fail(status) {
    if (!response.headersSent) {
      response.writeHead(status, { "Content-Type": "application/json; charset=utf-8" });
      response.end(JSON.stringify({ error: "채팅 서버에 연결할 수 없습니다." }));
    } else response.destroy();
    upstream.destroy();
  }
  const connectTimer = setTimeout(() => fail(504), connectMs);
  upstream.on("socket", socket => {
    if (socket.connecting) socket.once("connect", () => clearTimeout(connectTimer));
    else clearTimeout(connectTimer);
  });
  upstream.setTimeout(readMs, () => fail(504));
  upstream.on("response", incoming => {
    clearTimeout(connectTimer);
    const headers = { ...incoming.headers };
    delete headers.connection;
    delete headers["x-robots-tag"];
    response.writeHead(incoming.statusCode, headers);
    incoming.on("error", () => response.destroy());
    incoming.pipe(response);
  });
  upstream.on("error", () => { clearTimeout(connectTimer); if (!response.destroyed && !response.writableEnded) fail(502); });
  response.on("close", () => { clearTimeout(connectTimer); upstream.destroy(); });
  request.on("aborted", () => upstream.destroy());
  request.pipe(upstream);
  return true;
}
