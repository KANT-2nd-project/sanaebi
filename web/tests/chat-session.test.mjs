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

test("페이지 세션을 교체해도 공백과 줄바꿈을 포함한 초안만 복원한다", () => {
  let draft = "";
  const options = () => ({ initialDraft: draft, onDraftChange: value => { draft = value; } });
  const first = new ChatSession(undefined, options());
  first.changeDraft("  작성 중\n질문  ");
  first.dispose();
  const next = new ChatSession(undefined, options());
  assert.equal(next.state.draft, "  작성 중\n질문  ");
  assert.equal(next.getServerSnapshot().draft, next.state.draft);
  assert.deepEqual(next.state.turns, []);
  next.reset();
  assert.equal(draft, "");
});

test("보존 초안은 실패에 유지되고 성공에만 지워진다", async () => {
  let draft = "질문";
  let fail = true;
  const chat = new ChatSession(async () => { if (fail) throw Error("failed"); return "답변"; }, {
    initialDraft: draft, onDraftChange: value => { draft = value; },
  });
  await chat.submit();
  assert.equal(draft, "질문");
  fail = false;
  await chat.retry(chat.state.turns[0].id);
  assert.equal(draft, "");
});

test("이전 질문 재시도 성공은 새로 작성한 보존 초안을 지우지 않는다", async () => {
  let draft = "";
  let fail = true;
  const chat = new ChatSession(async () => { if (fail) throw Error("failed"); return "답변"; }, {
    onDraftChange: value => { draft = value; },
  });
  chat.changeDraft("이전 질문"); await chat.submit();
  chat.changeDraft("새 질문"); fail = false;
  await chat.retry(chat.state.turns[0].id);
  assert.equal(draft, "새 질문");
});

test("페이지 이탈 뒤 늦은 응답이 새 페이지의 보존 초안을 지우지 않는다", async () => {
  let draft = "";
  let signal;
  const d = deferred();
  const options = () => ({ initialDraft: draft, onDraftChange: value => { draft = value; } });
  const first = new ChatSession((_q, s) => { signal = s; return d.promise; }, options());
  first.changeDraft("전송 중 질문");
  const pending = first.submit(); first.dispose();
  assert.equal(signal.aborted, true);
  assert.equal(draft, "전송 중 질문");
  const next = new ChatSession(undefined, options()); next.changeDraft("새 페이지 입력");
  d.resolve("늦은 답변"); await pending;
  assert.equal(draft, "새 페이지 입력");
  assert.equal(next.state.activeTurnId, null);
});

test("독립 저장소와 기본 세션은 초안을 공유하지 않는다", () => {
  let a = "A", b = "B";
  const first = new ChatSession(undefined, { initialDraft: a, onDraftChange: value => { a = value; } });
  const second = new ChatSession(undefined, { initialDraft: b, onDraftChange: value => { b = value; } });
  first.reset();
  assert.equal(a, ""); assert.equal(b, "B");
  assert.equal(second.state.draft, "B");
  assert.equal(new ChatSession().state.draft, "");
});
