import { test } from "node:test";
import assert from "node:assert/strict";
import { ChatSession } from "../../tmp/frontend-unit-tests/features/question/chat-session.js";
import { askQuestion, QuestionError } from "../../tmp/frontend-unit-tests/lib/api/questions.js";

test("429 안내와 입력을 보존하고 자동 재호출하지 않는다", async () => {
  let calls = 0;
  const message = "오늘 생성 한도에 도달했습니다. 자정 이후 다시 시도해주세요.";
  const chat = new ChatSession(async () => {
    calls++;
    throw new QuestionError("rate-limit", message);
  });
  chat.changeDraft("휴가 절차");
  await chat.submit();
  assert.equal(calls, 1);
  assert.equal(chat.state.draft, "휴가 절차");
  assert.equal(chat.state.turns[0].error.message, message);
});

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
  assert.equal(chat.state.draft, "요청 중 수정"); assert.equal(calls, 1);
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

test("전송으로 비운 보존 초안은 실패 시 복원되고 재시도 성공 후 비어 있다", async () => {
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
  assert.equal(draft, "");
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

test("전송 시작 즉시 입력과 보존 초안을 비우며 실패에 원문을 복원한다", async () => {
  const d = deferred(); let draft = "  질문\n원문  ", calls = 0;
  const original = draft;
  const chat = new ChatSession((q) => { calls++; assert.equal(q, original.trim()); return d.promise; }, {
    initialDraft: draft, onDraftChange: value => { draft = value; },
  });
  const pending = chat.submit();
  assert.equal(chat.state.draft, "");
  assert.equal(draft, "");
  assert.equal(chat.state.turns[0].question, original.trim());
  assert.equal(chat.state.turns[0].status, "pending");
  await chat.submit(); await chat.retry(chat.state.turns[0].id);
  assert.equal(calls, 1);
  d.reject(new QuestionError("network", "연결 실패")); await pending;
  assert.equal(chat.state.draft, original); assert.equal(draft, original);
  assert.equal(chat.state.activeTurnId, null);
  assert.equal(chat.state.turns[0].status, "error");
});

for (const kind of ["network", "timeout", "validation", "rate-limit", "generation", "unavailable", "gateway", "invalid-response"]) {
  test(kind + " 실패는 비운 입력과 보존 초안을 복원한다", async () => {
    const d = deferred(); let saved = "  실패 질문  ";
    const chat = new ChatSession(() => d.promise, { initialDraft: saved, onDraftChange: v => { saved = v; } });
    const pending = chat.submit();
    assert.equal(saved, ""); assert.equal(chat.state.draft, "");
    d.reject(new QuestionError(kind, "모의 오류")); await pending;
    assert.equal(saved, "  실패 질문  "); assert.equal(chat.state.draft, saved);
    assert.equal(chat.state.activeTurnId, null); assert.equal(chat.state.turns.length, 1);
    assert.equal(chat.state.inputError, kind === "validation" ? "모의 오류" : "");
  });
}

test("별도 초안이 있는 이전 턴 재시도는 대기와 실패에도 입력을 유지한다", async () => {
  const d = deferred(); let count = 0, saved = "";
  const chat = new ChatSession(() => ++count === 1 ? Promise.reject(Error("fail")) : d.promise,
    { onDraftChange: v => { saved = v; } });
  chat.changeDraft("원래 질문"); await chat.submit();
  chat.changeDraft("별도 작성"); const run = chat.retry(chat.state.turns[0].id);
  assert.equal(saved, "별도 작성");
  await chat.retry(chat.state.turns[0].id); await chat.submit();
  assert.equal(count, 2);
  d.reject(Error("fail")); await run;
  assert.equal(saved, "별도 작성"); assert.equal(chat.state.draft, saved);
  assert.equal(chat.state.turns.length, 1);
});

for (const action of ["dispose", "reset"]) {
  test(action + " 뒤 늦은 실패는 입력을 복원하지 않는다", async () => {
    const d = deferred(); let saved = "";
    const chat = new ChatSession(() => d.promise, { onDraftChange: v => { saved = v; } });
    chat.changeDraft("이전 질문"); const run = chat.submit(); chat[action]();
    assert.equal(saved, "");
    chat.changeDraft("새 입력");
    d.reject(new QuestionError("network", "늦은 실패")); await run;
    assert.equal(saved, "새 입력"); assert.equal(chat.state.draft, saved);
  });
}

test("성공 시 입력을 다시 비우는 변경 알림을 보내지 않는다", async () => {
  const d = deferred(), changes = [];
  const chat = new ChatSession(() => d.promise, { initialDraft: "질문", onDraftChange: v => changes.push(v) });
  const pending = chat.submit(); assert.deepEqual(changes, [""]);
  d.resolve("답변"); await pending;
  assert.deepEqual(changes, [""]); assert.equal(chat.state.activeTurnId, null);
});

test("실제 전송 함수의 시간 초과는 요청을 중단하고 원문을 복원한다", async (t) => {
  let calls = 0, saved = "";
  t.mock.method(globalThis, "fetch", (_url, options) => new Promise((_resolve, reject) => {
    calls++;
    options.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true });
  }));
  const chat = new ChatSession((q, signal) => askQuestion(q, signal, 10), { onDraftChange: v => { saved = v; } });
  chat.changeDraft("  시간 초과 질문  ");
  const pending = chat.submit(); assert.equal(saved, "");
  await pending;
  assert.equal(calls, 1); assert.equal(saved, "  시간 초과 질문  ");
  assert.equal(chat.state.activeTurnId, null);
  assert.equal(chat.state.turns[0].error.kind, "timeout");
});

test("응답 대기 중 다음 초안을 작성하고 실패해도 보존한다", async () => {
  const d = deferred(); let saved = "";
  const chat = new ChatSession(() => d.promise, { onDraftChange: v => { saved = v; } });
  chat.changeDraft("보낸 질문"); const pending = chat.submit();
  chat.changeDraft("다음 질문");
  assert.equal(chat.state.draft, "다음 질문"); assert.equal(saved, "다음 질문");
  d.reject(new QuestionError("validation", "이전 질문 오류")); await pending;
  assert.equal(chat.state.draft, "다음 질문"); assert.equal(chat.state.inputError, "");
});

for (const kind of ["network", "timeout", "validation", "rate-limit", "generation", "unavailable"]) {
  for (const next of ["다음 질문", " \n ", ""]) {
    test(kind + " 응답 때 다음 입력 " + JSON.stringify(next) + " 보존/복원", async () => {
      const d = deferred(); let saved = "", calls = 0;
      const chat = new ChatSession(() => { calls++; return d.promise; }, { onDraftChange: v => { saved = v; } });
      chat.changeDraft("  제출 원문  "); const pending = chat.submit();
      chat.changeDraft("임시 작성"); chat.changeDraft(next);
      await chat.submit(); await chat.retry(chat.state.turns[0].id);
      assert.equal(calls, 1);
      d.reject(new QuestionError(kind, "원래 질문 오류")); await pending;
      assert.equal(saved, next === "" ? "  제출 원문  " : next);
      assert.equal(chat.state.draft, saved);
      assert.equal(chat.state.inputError, next === "" && kind === "validation" ? "원래 질문 오류" : "");
      assert.equal(chat.state.turns.length, 1);
    });
  }
}

test("성공해도 다음 초안을 유지하고 명시적으로 보내야 새 턴을 만든다", async () => {
  const d = deferred(); let calls = 0, saved = "";
  const chat = new ChatSession(() => ++calls === 1 ? d.promise : Promise.resolve("둘째 답변"), {
    onDraftChange: v => { saved = v; },
  });
  chat.changeDraft("첫 질문"); const pending = chat.submit();
  chat.changeDraft("둘째 질문"); await chat.submit(); assert.equal(calls, 1);
  d.resolve("첫 답변"); await pending;
  assert.equal(saved, "둘째 질문"); assert.equal(calls, 1);
  await chat.submit();
  assert.equal(calls, 2); assert.deepEqual(chat.state.turns.map(t => t.question), ["첫 질문", "둘째 질문"]);
});

test("재시도 중 바꾼 새 초안을 실패 응답이 덮어쓰지 않는다", async () => {
  const d = deferred(); let calls = 0;
  const chat = new ChatSession(() => ++calls === 1 ? Promise.reject(Error("fail")) : d.promise);
  chat.changeDraft("실패 질문"); await chat.submit();
  const pending = chat.retry(chat.state.turns[0].id);
  chat.changeDraft("재시도 중 새 질문");
  d.reject(new QuestionError("validation", "이전 오류")); await pending;
  assert.equal(chat.state.draft, "재시도 중 새 질문"); assert.equal(chat.state.inputError, "");
});

test("대기 중 작성한 초안은 이동 후 복원되고 늦은 실패는 무시된다", async () => {
  const d = deferred(); let saved = "";
  const options = () => ({ initialDraft: saved, onDraftChange: v => { saved = v; } });
  const chat = new ChatSession(() => d.promise, options());
  chat.changeDraft("전송 질문"); const pending = chat.submit();
  chat.changeDraft("대기 중 초안"); chat.dispose();
  const next = new ChatSession(undefined, options());
  assert.equal(next.state.draft, "대기 중 초안");
  d.reject(Error("late")); await pending;
  assert.equal(saved, "대기 중 초안");
  next.reset(); assert.equal(saved, "");
});
