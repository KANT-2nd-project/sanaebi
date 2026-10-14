import { test } from "node:test";
import assert from "node:assert/strict";
import { DocumentRouteState } from "../../tmp/frontend-unit-tests/features/documents/document-route-state.js";

test("취소한 back/forward 전환은 폼을 읽거나 초기화할 수 없고 이전 route 복구 후 다시 사용 가능하다", () => {
  const route = new DocumentRouteState("/admin/documents?id=A");
  let confirms = 0;
  const blocked = route.observe("/admin/documents?id=B", {
    dirty: true, pendingWrite: false, confirmDiscard: () => { confirms++; return false; },
  });
  assert.deepEqual(blocked, { kind: "blocked", reason: "unsaved-changes", restoreUrl: "/admin/documents?id=A" });
  assert.equal(route.canLoad("/admin/documents?id=B"), false);
  assert.equal(route.acceptedUrl, "/admin/documents?id=A");
  assert.deepEqual(route.observe("/admin/documents?id=A", { dirty: true, pendingWrite: false, confirmDiscard: () => true }), { kind: "same" });
  assert.equal(route.canLoad("/admin/documents?id=A"), true);
  assert.equal(confirms, 1);
});

test("저장 중에는 확인 없이 route 변경을 막고 수동 이동은 사전 승인 후 허용한다", () => {
  const route = new DocumentRouteState("/admin/documents?new=1");
  const blocked = route.observe("/admin/documents", {
    dirty: true, pendingWrite: true, confirmDiscard: () => { throw new Error("must not ask while writing"); },
  });
  assert.equal(blocked.kind, "blocked");
  assert.equal(blocked.reason, "pending-write");
  assert.equal(route.canLoad("/admin/documents"), false);

  route.approve("/admin/documents");
  assert.deepEqual(route.observe("/admin/documents", {
    dirty: true, pendingWrite: false, confirmDiscard: () => true,
  }), { kind: "accepted" });
  assert.equal(route.canLoad("/admin/documents"), true);
});

