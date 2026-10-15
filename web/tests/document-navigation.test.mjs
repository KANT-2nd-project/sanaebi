import { test } from "node:test";
import assert from "node:assert/strict";
import { allowDocumentNavigation } from "../../tmp/frontend-unit-tests/features/question/document-navigation.js";

const click = { button: 0, ctrlKey: false, metaKey: false, shiftKey: false, altKey: false };
const unused = () => { throw new Error("unexpected confirmation"); };

test("빈 대화와 작성 입력만 있으면 확인 없이 이동", () => {
  for (const draft of ["", "작성 중"])
    assert.equal(allowDocumentNavigation(click, { turns: [], activeTurnId: null, draft }, unused), true);
});

test("완료·실패·대기 턴에서 취소/확인을 그대로 반영하고 상태를 변경하지 않음", () => {
  for (const status of ["success", "error", "pending"]) {
    const state = { turns: [{ status }], activeTurnId: status === "pending" ? "1" : null };
    const before = structuredClone(state);
    for (const choice of [false, true]) {
      let calls = 0;
      assert.equal(allowDocumentNavigation(click, state, message => {
        calls++; assert.match(message, /대화 기록/); assert.match(message, /취소/); assert.match(message, /작성 중/);
        return choice;
      }), choice);
      assert.equal(calls, 1);
      assert.deepEqual(state, before);
    }
  }
});

test("턴이 없어도 진행 요청이 있으면 확인", () => {
  assert.equal(allowDocumentNavigation(click, { turns: [], activeTurnId: "1" }, () => false), false);
});

test("새 탭·새 창·보조 클릭은 브라우저 기본 동작", () => {
  const state = { turns: [{}], activeTurnId: "1" };
  for (const change of [{ctrlKey:true},{metaKey:true},{shiftKey:true},{altKey:true},{button:1}])
    assert.equal(allowDocumentNavigation({...click,...change}, state, unused), true);
});
