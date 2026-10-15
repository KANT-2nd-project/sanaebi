import { test } from "node:test";
import assert from "node:assert/strict";
import { createDocument, listDocuments, maintainDocuments, publishDocument, updateDocument, withdrawDocument } from "../../tmp/frontend-unit-tests/lib/api/documents.js";

const revision = {
  id: "revision-1", revision_number: 1, title: "휴가 안내", body: "연차를 신청합니다.",
  source_label: "공통 자료", source_url: null, owner_department: null, effective_from: null,
  content_hash: "a".repeat(64), created_at: "2026-10-14T00:00:00Z",
};
const detail = {
  id: "document-1", record_version: 1, withdrawn: false,
  created_at: "2026-10-14T00:00:00Z", updated_at: "2026-10-14T00:00:00Z",
  status: "draft", eligibility: "draft", draft: revision, published: null,
};

test("목록 조회는 필터와 페이지를 전달하고 본문 캐시를 금지한다", async (t) => {
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.equal(url, "/api/documents?q=%ED%9C%B4%EA%B0%80&status=draft&limit=20&offset=40");
    assert.equal(options.method, "GET");
    assert.equal(options.cache, "no-store");
    assert.equal(options.headers.get("Cache-Control"), "no-store");
    return Response.json({ items: [], total: 0 });
  });
  assert.deepEqual(await listDocuments({ q: "휴가", status: "draft", limit: 20, offset: 40 }), { items: [], total: 0 });
});

test("신규 저장은 멱등성 키와 모든 문서 메타데이터를 보내고 detail을 검증한다", async (t) => {
  const payload = {
    title: "휴가 안내", body: "연차를 신청합니다.", source_label: "공통 자료",
    source_url: null, owner_department: "인사", effective_from: "2026-11-01",
  };
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.equal(url, "/api/documents");
    assert.equal(options.method, "POST");
    assert.equal(options.headers.get("Idempotency-Key"), "4b203a6b-655a-46f2-a836-273fc80528fe");
    assert.deepEqual(JSON.parse(options.body), payload);
    return Response.json(detail, { status: 201 });
  });
  assert.equal((await createDocument(payload, "4b203a6b-655a-46f2-a836-273fc80528fe")).id, "document-1");
});

test("편집·게시·사용 중단은 expected_version과 revision을 멱등 키로 보낸다", async (t) => {
  const payload = {
    title: "휴가 안내", body: "연차를 신청합니다.", source_label: "공통 자료",
    source_url: null, owner_department: "인사", effective_from: null,
  };
  t.mock.method(globalThis, "fetch", async (url, options) => {
    const body = JSON.parse(options.body);
    assert.equal(options.headers.get("Idempotency-Key"), "4b203a6b-655a-46f2-a836-273fc80528fe");
    if (url === "/api/documents/document-1") {
      assert.equal(options.method, "PATCH");
      assert.deepEqual(body, { expected_version: 7, ...payload });
    } else if (url === "/api/documents/document-1/publish") {
      assert.equal(options.method, "POST");
      assert.deepEqual(body, { expected_version: 8, revision_id: "revision-1" });
    } else {
      assert.equal(url, "/api/documents/document-1/withdraw");
      assert.deepEqual(body, { expected_version: 9 });
    }
    return Response.json(detail, { status: 200 });
  });
  await updateDocument("document-1", 7, payload, "4b203a6b-655a-46f2-a836-273fc80528fe");
  await publishDocument("document-1", 8, "revision-1", "4b203a6b-655a-46f2-a836-273fc80528fe");
  await withdrawDocument("document-1", 9, "4b203a6b-655a-46f2-a836-273fc80528fe");
});

test("형태가 잘못된 detail 응답은 성공처럼 반환하지 않는다", async (t) => {
  t.mock.method(globalThis, "fetch", async () => Response.json({ ...detail, draft: { ...revision, body: 5 } }, { status: 201 }));
  await assert.rejects(createDocument({ title: "x", body: "y", source_label: "x" }, "4b203a6b-655a-46f2-a836-273fc80528fe"), { kind: "invalid-response" });
});

test("409 API 오류는 코드와 details를 보존한다", async (t) => {
  t.mock.method(globalThis, "fetch", async () => Response.json({
    ok: false, error: { code: "revision_conflict", message: "최신 문서가 있습니다.", details: { record_version: 3 } },
  }, { status: 409 }));
  await assert.rejects(listDocuments(), error => error.kind === "conflict" && error.code === "revision_conflict" && error.details.record_version === 3);
});

test("35초 timeout 경계는 요청을 한 번만 취소한다", async (t) => {
  let calls = 0;
  t.mock.method(globalThis, "fetch", (_url, options) => new Promise((_resolve, reject) => {
    calls++;
    options.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true });
  }));
  await assert.rejects(listDocuments({}, { timeoutMs: 10 }), error => error.kind === "timeout" && error.message.startsWith("1초 동안 응답이 없어"));
  assert.equal(calls, 1);
});

test("색인 동기화 요청은 caller signal과 함께 180초 대기 한도를 사용한다", async (t) => {
  const delays = [];
  const originalSetTimeout = globalThis.setTimeout;
  t.mock.method(globalThis, "setTimeout", (callback, delay, ...args) => {
    delays.push(delay);
    return originalSetTimeout(callback, delay, ...args);
  });
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.ok(options.signal instanceof AbortSignal);
    return url === "/api/documents/maintenance"
      ? Response.json({ action: "clear", deleted_count: 1, restored_count: 0, completed_at: "2026-10-16T00:00:00Z" })
      : Response.json(detail);
  });
  const signal = new AbortController().signal;
  await publishDocument("document-1", 8, "revision-1", "publish-key", { signal });
  await withdrawDocument("document-1", 8, "withdraw-key", { signal });
  await maintainDocuments({ action: "clear", total_count: 1, restored_count: 0, expected_state: "a".repeat(64) }, "maintenance-key", { signal });
  assert.deepEqual(delays, [180_000, 180_000, 180_000]);
});

test("게시 색인 실패는 부분 저장 상태를 보존하고 같은 키·본문 재시도로 검색 반영을 확인한다", async (t) => {
  let calls = 0;
  const sent = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls++;
    sent.push({ url, key: options.headers.get("Idempotency-Key"), body: options.body });
    if (calls === 1) return Response.json({
      ok: false,
      error: {
        code: "retrieval_sync_failed",
        message: "문서는 저장됐지만 검색 반영이 완료되지 않았습니다.",
        details: { document_saved: true, retryable: true },
      },
    }, { status: 503 });
    return Response.json(detail);
  });

  await assert.rejects(publishDocument("document-1", 8, "revision-1", "same-key"), error => {
    assert.equal(error.kind, "retrieval-sync");
    assert.equal(error.code, "retrieval_sync_failed");
    assert.equal(error.details.document_saved, true);
    assert.equal(error.details.retryable, true);
    return true;
  });
  await publishDocument("document-1", 8, "revision-1", "same-key");

  assert.equal(calls, 2);
  assert.deepEqual(sent[1], sent[0]);
});

test("사용 중단 색인 실패도 같은 요청 키와 expected_version으로 재시도한다", async (t) => {
  let calls = 0;
  const sent = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls++;
    sent.push({ url, key: options.headers.get("Idempotency-Key"), body: options.body });
    if (calls === 1) return Response.json({
      ok: false,
      error: {
        code: "retrieval_sync_failed",
        message: "문서 변경은 적용됐지만 검색 반영이 완료되지 않았습니다.",
        details: { document_saved: true, retryable: true },
      },
    }, { status: 503 });
    return Response.json(detail);
  });

  await assert.rejects(withdrawDocument("document-1", 9, "same-key"), { kind: "retrieval-sync" });
  await withdrawDocument("document-1", 9, "same-key");
  assert.equal(calls, 2);
  assert.equal(sent[0].url, "/api/documents/document-1/withdraw");
  assert.deepEqual(sent[1], sent[0]);
});

test("전체 문서 색인 반영 실패도 동일한 멱등 키와 preview 본문으로 재시도한다", async (t) => {
  let calls = 0;
  const sent = [];
  const result = { action: "restore", deleted_count: 71, restored_count: 71, completed_at: "2026-10-16T00:00:00Z" };
  t.mock.method(globalThis, "fetch", async (_url, options) => {
    calls++;
    sent.push({ key: options.headers.get("Idempotency-Key"), body: options.body });
    if (calls === 1) return Response.json({
      ok: false,
      error: {
        code: "retrieval_sync_failed",
        message: "문서 변경은 적용됐지만 검색 반영이 완료되지 않았습니다.",
        details: { document_saved: true, retryable: true },
      },
    }, { status: 503 });
    return Response.json(result);
  });

  await assert.rejects(maintainDocuments({ action: "restore", total_count: 4, restored_count: 71, expected_state: "a".repeat(64) }, "same-key"), error => {
    assert.equal(error.kind, "retrieval-sync");
    assert.equal(error.details.document_saved, true);
    return true;
  });
  assert.deepEqual(await maintainDocuments({ action: "restore", total_count: 4, restored_count: 71, expected_state: "a".repeat(64) }, "same-key"), result);

  assert.equal(calls, 2);
  assert.deepEqual(sent[1], sent[0]);
});

test("응답 body를 읽는 중 timeout은 성공으로 처리하지 않는다", async (t) => {
  t.mock.method(globalThis, "fetch", async (_url, options) => ({
    status: 200,
    headers: new Headers({ "Content-Type": "application/json" }),
    json: () => new Promise((_resolve, reject) => options.signal.addEventListener(
      "abort", () => reject(new DOMException("aborted", "AbortError")), { once: true },
    )),
  }));
  await assert.rejects(listDocuments({}, { timeoutMs: 10 }), { kind: "timeout" });
});


test("원본 출처와 검수 메타데이터를 보존하고 잘못된 배열을 거부한다", async (t) => {
  const metadata = { category: "people_leave", source_version: "2.0.0", review_status: "ai_reviewed", source_ids: ["H01"], policy_decision_ids: ["D01"] };
  const provenance = { source_namespace: "company-knowledge-v2", source_document_id: "ieum-001", source_file_sha256: "a".repeat(64), row_sha256: "b".repeat(64), imported_at: "2026-10-14T00:00:00Z" };
  let payload = { ...detail, draft: { ...revision, metadata }, provenance };
  t.mock.method(globalThis, "fetch", async () => Response.json(payload, { status: 201 }));
  const result = await createDocument({ title: "x", body: "y", source_label: "x" }, "key");
  assert.deepEqual(result.draft.metadata, metadata);
  assert.deepEqual(result.provenance, provenance);
  payload = { ...payload, draft: { ...revision, metadata: { ...metadata, source_ids: [1] } } };
  await assert.rejects(createDocument({ title: "x", body: "y", source_label: "x" }, "key"), { kind: "invalid-response" });
});
