import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
const require = createRequire(import.meta.url);
const loader = require("../scripts/tailwind-loader.cjs");
const dir = fileURLToPath(new URL("..", import.meta.url));
const resourcePath = fileURLToPath(new URL("../app/globals.css", import.meta.url));

function transform(value) {
  return new Promise((resolve, reject) => {
    loader.call({
      resourcePath, resource: resourcePath,
      getOptions: () => ({ base: dir }),
      addDependency() {}, addContextDependency() {},
      async: () => (error, css) => error ? reject(error) : resolve(css),
    }, `@import "tailwindcss"; :root { --loader-regression: ${value}; }`);
  });
}

test("동일 파일 경로와 mtime에서도 새 CSS 입력을 이전 컴파일 결과로 대체하지 않는다", async () => {
  const first = await transform("first");
  const second = await transform("second");
  assert.match(first, /--loader-regression: first/);
  assert.match(second, /--loader-regression: second/);
  assert.doesNotMatch(second, /--loader-regression: first/);
});
