import { test } from "node:test";
import assert from "node:assert/strict";
import { previewDocumentMaintenance, maintainDocuments } from "../../tmp/frontend-unit-tests/lib/api/documents.js";

const preview = { action: "clear", total_count: 71, restored_count: 0, expected_state: "a".repeat(64) };
test("전체 관리 미리보기는 목록 필터 없이 전체 상태를 조회한다", async (t) => {
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.equal(url, "/api/documents/maintenance-preview?action=clear");
    assert.equal(options.method, "GET");
    assert.equal(options.cache, "no-store");
    return Response.json(preview);
  });
  assert.deepEqual(await previewDocumentMaintenance("clear"), preview);
});
test("전체 관리 쓰기는 상태 확인값과 동일한 키만 전송한다", async (t) => {
  let calls = 0;
  const result = { action: "clear", deleted_count: 71, restored_count: 0, completed_at: "2026-10-15T00:00:00Z" };
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls++;
    assert.equal(url, "/api/documents/maintenance");
    assert.equal(options.headers.get("Idempotency-Key"), "fixed-key");
    assert.deepEqual(JSON.parse(options.body), { action: "clear", expected_state: preview.expected_state });
    return Response.json(result);
  });
  assert.deepEqual(await maintainDocuments(preview, "fixed-key"), result);
  assert.equal(calls, 1);
});
test("통신 실패 자동 재시도 없이 반환하고 잘못된 확인값을 거부한다", async (t) => {
  let calls = 0;
  t.mock.method(globalThis, "fetch", async () => { calls++; throw new TypeError("network"); });
  await assert.rejects(maintainDocuments(preview, "fixed-key"));
  assert.equal(calls, 1);
  t.mock.restoreAll();
  t.mock.method(globalThis, "fetch", async () => Response.json({ ...preview, expected_state: "invalid" }));
  await assert.rejects(previewDocumentMaintenance("clear"));
});
