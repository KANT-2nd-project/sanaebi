import { test } from "node:test";
import assert from "node:assert/strict";
import { parseDocumentView, documentViewUrl, selectedRevision, hasDraftChanges, eligibilityLabel } from "../../tmp/frontend-unit-tests/features/documents/document-view-state.js";

test("검색 조건과 편집 경로는 인코딩 후 복원된다", () => {
  const view = parseDocumentView("q=연차%26휴가&status=published&page=4&id=A&mode=edit");
  assert.deepEqual(parseDocumentView(documentViewUrl(view).split("?")[1]), view);
  const list = { ...view, id: null, editing: false, isNew: false, revision: null };
  assert.equal(documentViewUrl(list), "/admin/documents?q=%EC%97%B0%EC%B0%A8%26%ED%9C%B4%EA%B0%80&status=published&page=4");
});
test("잘못된 페이지·모드·상태는 유효한 목록으로 정규화된다", () => {
  for (const page of ["0", "-1", "1.5", "Infinity", "9007199254740992", "x"]) {
    assert.equal(parseDocumentView(`page=${page}&status=x&mode=edit`).page, 1);
    assert.equal(documentViewUrl(parseDocumentView(`page=${page}&status=x&mode=edit`)), "/admin/documents");
  }
  assert.equal(parseDocumentView("id=A&new=1").isNew, false);
  assert.equal(parseDocumentView("new=1").editing, true);
});
test("기본 읽기는 게시본이고 초안 탭은 해당 개정만 선택한다", () => {
  const detail = { draft: { id: "v2", body: "수정", metadata: { review_status: "unreviewed" } }, published: { id: "v1", body: "현재", metadata: { review_status: "ai_reviewed" } } };
  assert.equal(selectedRevision(detail, null), detail.published);
  assert.equal(selectedRevision(detail, "draft"), detail.draft);
  assert.equal(selectedRevision({ ...detail, published: null }, "published"), detail.draft);
  assert.equal(hasDraftChanges(detail), true);
  assert.equal(hasDraftChanges({ ...detail, draft: detail.published }), false);
  assert.equal(eligibilityLabel("scheduled"), "시행일 대기");
  assert.equal(eligibilityLabel("withdrawn"), "사용 중단 · 답변 제외");
});
