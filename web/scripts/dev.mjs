import { createServer } from "node:http";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import { applyApiNoStore } from "./dev-response.mjs";

// This launcher is development-only; deployment still uses static export + nginx.
process.env.NODE_ENV = "development";
const { values } = parseArgs({ options: {
  hostname: { type: "string", short: "H", default: "0.0.0.0" },
  port: { type: "string", short: "p", default: process.env.PORT || "3000" },
} });
const port = Number(values.port);
if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error("Invalid development port");
const { default: next } = await import("next");
const app = next({ dev: true, dir: fileURLToPath(new URL("..", import.meta.url)), hostname: values.hostname, port });
await app.prepare();
const handle = app.getRequestHandler();
const server = createServer((request, response) => {
  const pathname = (request.url || "/").split("?")[0];
  if (pathname === "/api" || pathname.startsWith("/api/")) applyApiNoStore(response);
  handle(request, response).catch(() => {
    if (!response.headersSent) response.writeHead(500);
    if (!response.writableEnded) response.end("Internal Server Error");
  });
});
// Next attaches its HMR upgrade handler on the first HTTP request.
const sockets = new Set();
server.on("connection", socket => {
  sockets.add(socket);
  socket.once("close", () => sockets.delete(socket));
});
server.on("error", error => { console.error(error.message); process.exit(1); });
server.listen(port, values.hostname, () => console.log(`Development: http://localhost:${port} (API → 127.0.0.1:8000)`));
let closing = false;
async function close() {
  if (closing) return;
  closing = true;
  server.close();
  for (const socket of sockets) socket.destroy();
  await app.close();
  process.exit(0);
}
process.once("SIGINT", close);
process.once("SIGTERM", close);
