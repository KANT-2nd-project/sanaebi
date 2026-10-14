import { test } from "node:test";
import assert from "node:assert/strict";
import { ChatSession } from "../../tmp/frontend-unit-tests/features/question/chat-session.js";

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

test("두 질문을 누적하고 draft 편집으로 기존 답변을 지우지 않는다", async () => {
  const chat = new ChatSession(async (q) => q);
  chat.changeDraft(" 첫 질문 "); await chat.submit();
  chat.changeDraft("둘째 질문");
  assert.equal(chat.state.turns[0].answer, "첫 질문");
  await chat.submit();
  assert.deepEqual(chat.state.turns.map(t => t.answer), ["첫 질문", "둘째 질문"]);
  assert.equal(chat.state.draft, "");
});

test("공백은 요청 없이 검증하고 Enter 중복 제출은 한 요청만 보낸다", async () => {
  const d = deferred(); let calls = 0;
  const chat = new ChatSession(() => { calls++; return d.promise; });
  chat.changeDraft("  "); await chat.submit();
  assert.equal(chat.state.inputError, "질문을 입력해주세요"); assert.equal(calls, 0);
  chat.changeDraft("질문"); const first = chat.submit(); const duplicate = chat.submit();
  chat.changeDraft("요청 중 수정");
  assert.equal(chat.state.draft, "질문"); assert.equal(calls, 1);
  d.resolve("답변"); await Promise.all([first, duplicate]);
  assert.equal(chat.state.turns.length, 1);
});

test("실패한 같은 질문은 기존 턴을 재시도하고 수정한 질문은 새 턴이다", async () => {
  let fail = true;
  const chat = new ChatSession(async () => { if (fail) throw Error("private"); return "성공"; });
  chat.changeDraft("질문"); await chat.submit();
  const id = chat.state.turns[0].id;
  assert.equal(chat.state.draft, "질문"); assert.equal(chat.state.turns[0].status, "error");
  fail = false; await chat.submit();
  assert.equal(chat.state.turns.length, 1); assert.equal(chat.state.turns[0].id, id);
  fail = true; chat.changeDraft("실패 질문"); await chat.submit();
  fail = false; chat.changeDraft("수정 질문"); await chat.submit();
  assert.equal(chat.state.turns.length, 3);
});

test("메시지 재시도는 별도로 작성한 draft를 지우지 않는다", async () => {
  let fail = true;
  const chat = new ChatSession(async q => { if (fail) throw Error("fail"); return q; });
  chat.changeDraft("원본"); await chat.submit();
  const id = chat.state.turns[0].id;
  chat.changeDraft("새로 작성 중"); fail = false; await chat.retry(id);
  assert.equal(chat.state.draft, "새로 작성 중");
  assert.equal(chat.state.turns[0].answer, "원본");
});

test("새 대화는 요청을 취소하고 늦은 응답이 새 턴을 변경하지 못한다", async () => {
  const first = deferred(), next = deferred(); let signal; let count = 0;
  const chat = new ChatSession((q, s) => { if (++count === 1) { signal = s; return first.promise; } return next.promise; });
  chat.changeDraft("예전 질문"); const oldRun = chat.submit(); chat.reset();
  assert.equal(signal.aborted, true);
  chat.changeDraft("새 질문"); const newRun = chat.submit();
  first.resolve("늦은 답변"); await oldRun;
  assert.equal(chat.state.turns.length, 1); assert.equal(chat.state.turns[0].status, "pending");
  next.resolve("새 답변"); await newRun;
  assert.equal(chat.state.turns[0].answer, "새 답변");
});
