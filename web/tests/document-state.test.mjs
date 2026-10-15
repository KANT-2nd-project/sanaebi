import { test } from "node:test";
import assert from "node:assert/strict";
import {
  canRetryDocumentWrite, emptyDocumentForm, formFromRevision, isDocumentFormDirty, nextWriteAttempt,
  documentPayload, newIdempotencyKey, reconcileDocumentDetail, validateDocumentForm,
  retrievalSyncFailureMessage,
} from "../../tmp/frontend-unit-tests/features/documents/document-state.js";
import { DocumentApiError } from "../../tmp/frontend-unit-tests/lib/api/documents.js";

const revision = (title, body = "내용") => ({
  id: "revision-1", revision_number: 1, title, body, source_label: "공통 자료", source_url: null,
  owner_department: null, effective_from: null, content_hash: "a".repeat(64), created_at: "2026-10-14T00:00:00Z",
});
const detail = (title, version) => ({
  id: "document-1", record_version: version, withdrawn: false, created_at: "2026-10-14T00:00:00Z",
  updated_at: "2026-10-14T00:00:00Z", status: "draft", eligibility: "draft",
  draft: revision(title), published: null,
});

test("양식 dirty 판정은 metadata까지 저장 문자열 그대로 비교한다", () => {
  const form = formFromRevision(revision("휴가 안내"));
  assert.equal(isDocumentFormDirty(form, { ...form }), false);
  assert.equal(isDocumentFormDirty({ ...form, owner_department: "인사" }, form), true);
  assert.equal(isDocumentFormDirty({ ...form, body: "내용\n" }, form), true);
});

test("충돌의 최신 detail은 따로 보관하고 작성 중인 폼을 덮지 않는다", () => {
  const original = detail("휴가 안내", 1);
  const baselineForm = formFromRevision(original.draft);
  const localForm = { ...baselineForm, title: "내가 편집한 제목" };
  const latest = detail("다른 작성자의 제목", 2);
  const result = reconcileDocumentDetail({ detail: original, form: localForm, baselineForm }, latest);
  assert.equal(result.form.title, "내가 편집한 제목");
  assert.equal(result.latestDetail, latest);
  assert.equal(result.conflict, true);
});

test("같은 payload 수동 재시도는 키를 보존하고 payload 변경은 새 키를 만든다", () => {
  const keys = ["key-1", "key-2"];
  const nextKey = () => keys.shift();
  const first = nextWriteAttempt(null, "POST", "/api/documents", { title: "A" }, nextKey);
  const retry = nextWriteAttempt(first, "POST", "/api/documents", { title: "A" }, nextKey);
  const changed = nextWriteAttempt(retry, "POST", "/api/documents", { title: "B" }, nextKey);
  assert.equal(retry.key, "key-1");
  assert.equal(changed.key, "key-2");
});

test("등록 양식은 제목·본문과 metadata 형식을 검증한다", () => {
  const form = emptyDocumentForm();
  assert.ok(validateDocumentForm(form).title);
  assert.ok(validateDocumentForm(form).body);
  assert.deepEqual(validateDocumentForm({
    ...form, title: "휴가 안내", body: "원문", source_url: "javascript:alert(1)", effective_from: "2026-02-31",
  }), { source_url: "http:// 또는 https:// 출처 주소를 입력해주세요", effective_from: "실제 날짜를 입력해주세요" });
});

test("선택 메타데이터 빈 값은 null로 보내고 원문 개행은 보존한다", () => {
  const form = { ...emptyDocumentForm(), title: "휴가 안내", body: "첫 줄\n둘째 줄", source_label: "" };
  assert.deepEqual(documentPayload(form), {
    title: "휴가 안내", body: "첫 줄\n둘째 줄", source_label: "",
    source_url: null, owner_department: null, effective_from: null,
  });
});

test("새 멱등성 키는 표준 UUID 형식이다", () => {
  assert.match(newIdempotencyKey(), /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
});

test("검색 반영 실패는 변경 보존을 알리고 retryable일 때만 재시도를 허용한다", () => {
  const failed = new DocumentApiError("retrieval-sync", "backend detail", "retrieval_sync_failed", {
    document_saved: true, retryable: true,
  });
  assert.equal(canRetryDocumentWrite(failed), true);
  assert.match(retrievalSyncFailureMessage(failed), /문서 변경은 적용됐지만 검색 반영이 끝나지 않았습니다/);
  assert.match(retrievalSyncFailureMessage(failed), /같은 요청으로 검색 반영을 다시 확인/);

  const preflightFailed = new DocumentApiError("retrieval-sync", "backend detail", "retrieval_sync_failed", {
    document_saved: false, retryable: true,
  });
  assert.equal(canRetryDocumentWrite(preflightFailed), true);
  assert.match(retrievalSyncFailureMessage(preflightFailed), /문서 변경은 시작되지 않았습니다/);

  const busy = new DocumentApiError("retrieval-sync", "backend detail", "retrieval_sync_busy", {
    document_saved: false, retryable: true,
  });
  assert.equal(canRetryDocumentWrite(busy), true);
  assert.match(retrievalSyncFailureMessage(busy), /이전 요청이 있었다면 저장됐을 수/);
});
