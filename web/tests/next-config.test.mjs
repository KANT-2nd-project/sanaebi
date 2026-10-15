import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { PHASE_DEVELOPMENT_SERVER, PHASE_PRODUCTION_BUILD } from "next/constants.js";
import { transpileConfig } from "next/dist/build/next-config-ts/transpile-config.js";

const { default: config } = await transpileConfig({
  nextConfigPath: fileURLToPath(new URL("../next.config.ts", import.meta.url)),
  dir: fileURLToPath(new URL("..", import.meta.url)),
});

test("개발 서버는 동일 출처 API를 중계하고 오래된 디스크 CSS를 복원하지 않는다", async () => {
  const dev = config(PHASE_DEVELOPMENT_SERVER);
  assert.equal(dev.output, undefined);
  assert.deepEqual(await dev.rewrites(), [
    { source: "/api/:path*", destination: "http://127.0.0.1:8000/:path*" },
  ]);
  assert.equal(dev.experimental.proxyTimeout, 210_000);
  assert.equal(dev.experimental.turbopackFileSystemCacheForDev, false);
});

test("upstream 지연을 위한 배포·개발 기본값과 생성 코드 reload 경로를 유지한다", async () => {
  const nginx = await readFile(new URL("../../deployment/nginx.conf", import.meta.url), "utf8");
  const packageJson = JSON.parse(await readFile(new URL("../../package.json", import.meta.url), "utf8"));
  assert.match(nginx, /proxy_read_timeout 210s;/);
  assert.match(packageJson.scripts["dev:api"], /--reload-dir generation/);
});

test("정적 빌드는 개발용 중계 없이 export하고 기존 Tailwind 로더를 유지한다", () => {
  const build = config(PHASE_PRODUCTION_BUILD);
  assert.equal(build.output, "export");
  assert.equal(build.rewrites, undefined);
  assert.equal(build.headers, undefined);
  assert.equal(build.experimental, undefined);
  assert.deepEqual(build.turbopack.rules["*.css"].loaders, ["./scripts/tailwind-loader.cjs"]);
});
