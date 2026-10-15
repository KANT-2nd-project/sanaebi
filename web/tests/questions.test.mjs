import { test } from "node:test";
import assert from "node:assert/strict";
import { askQuestion, QUESTION_TIMEOUT_MS } from "../../tmp/frontend-unit-tests/lib/api/questions.js";

test("question JSON만 전송하고 검증된 본문을 반환한다", async (t) => {
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.equal(url, "/api/ask");
    assert.equal(options.method, "POST");
    assert.deepEqual(JSON.parse(options.body), { question: "휴가 안내" });
    assert.equal(options.cache, "no-store");
    return Response.json({ ok: true, text: "안내\n둘째 줄", reason: "" });
  });
  assert.equal(await askQuestion("휴가 안내", new AbortController().signal), "안내\n둘째 줄");
});

const signal = () => new AbortController().signal;
for (const [status, kind] of [[422, "validation"], [429, "rate-limit"], [502, "generation"]]) {
  test(`${status}의 안전한 reason을 유지한다`, async (t) => {
    t.mock.method(globalThis, "fetch", async () => Response.json(
      { ok: false, text: "", reason: "안전한 안내" }, { status },
    ));
    await assert.rejects(askQuestion("질문", signal()), { kind, message: "안전한 안내" });
  });
}
test("분류·문서 준비 실패 503은 서버의 안전한 안내를 보존한다", async (t) => {
  t.mock.method(globalThis, "fetch", async () => Response.json(
    { ok: false, text: "", reason: "분류 서비스를 준비하지 못했습니다." }, { status: 503 },
  ));
  await assert.rejects(askQuestion("질문", signal()), {
    kind: "unavailable", message: "분류 서비스를 준비하지 못했습니다.",
  });
});
for (const body of [null, [], {}, { ok: true, text: null, reason: "" },
  { ok: true, text: "   ", reason: "" }, { ok: false, text: "", reason: "내부 오류" },
  { ok: true, text: "답변" }]) {
  test(`잘못된 200 envelope 차단: ${JSON.stringify(body)}`, async (t) => {
    t.mock.method(globalThis, "fetch", async () => Response.json(body));
    await assert.rejects(askQuestion("질문", signal()), { kind: "invalid-response" });
  });
}
for (const status of [502, 504]) {
  test(`${status} HTML 원문 미노출`, async (t) => {
    t.mock.method(globalThis, "fetch", async () => new Response("<html>secret upstream</html>", {
      status, headers: { "Content-Type": "text/html" },
    }));
    await assert.rejects(askQuestion("질문", signal()), e => e.kind === "gateway" && !e.message.includes("secret"));
  });
}
test("손상된 JSON은 안전한 오류", async (t) => {
  t.mock.method(globalThis, "fetch", async () => new Response("{secret", { headers: { "Content-Type": "application/json" } }));
  await assert.rejects(askQuestion("질문", signal()), { kind: "invalid-response" });
});
for (const status of [404, 405, 500]) {
  test(`${status}는 성공 envelope여도 실패`, async (t) => {
    t.mock.method(globalThis, "fetch", async () => Response.json({ ok: true, text: "secret", reason: "" }, { status }));
    await assert.rejects(askQuestion("질문", signal()), { kind: "request" });
  });
}
test("502의 ok=true는 계약 오류", async (t) => {
  t.mock.method(globalThis, "fetch", async () => Response.json({ ok: true, text: "답변", reason: "" }, { status: 502 }));
  await assert.rejects(askQuestion("질문", signal()), { kind: "invalid-response" });
});
test("연결 실패는 원문 대신 안전한 문구이며 자동 재호출하지 않는다", async (t) => {
  let count = 0;
  t.mock.method(globalThis, "fetch", async () => { count++; throw new Error("secret token"); });
  await assert.rejects(askQuestion("질문", signal()), e => e.kind === "network" && !e.message.includes("secret"));
  assert.equal(count, 1);
});
test("헤더 charset 처리와 정상 한계 안내의 원문 유지", async (t) => {
  const text = "자료가 부족합니다.\n<script>alert(1)</script>";
  t.mock.method(globalThis, "fetch", async () => new Response(JSON.stringify({ok:true,text,reason:""}), {
    headers: { "Content-Type": "Application/JSON; charset=utf-8" },
  }));
  assert.equal(await askQuestion("질문", signal()), text);
});
test("시간 초과는 fetch를 중단하고 재호출하지 않는다", async (t) => {
  let count = 0;
  t.mock.method(globalThis, "fetch", (_url, options) => new Promise((_resolve, reject) => {
    count++;
    options.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once:true });
  }));
  await assert.rejects(askQuestion("질문", signal(), 10), { kind: "timeout" });
  assert.equal(count, 1);
});
test("웹의 기본 답변 대기 한도는 240초다", () => {
  assert.equal(QUESTION_TIMEOUT_MS, 240_000);
});
test("화면 이탈 취소는 timeout과 구분한다", async (t) => {
  const controller = new AbortController();
  t.mock.method(globalThis, "fetch", (_url, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once:true });
  }));
  const request = askQuestion("질문", controller.signal);
  controller.abort();
  await assert.rejects(request, { kind: "aborted" });
});
test("이미 취소된 요청은 전송하지 않는다", async (t) => {
  const mock = t.mock.method(globalThis, "fetch", () => { throw new Error("must not fetch"); });
  const controller = new AbortController(); controller.abort();
  await assert.rejects(askQuestion("질문", controller.signal), { kind: "aborted" });
  assert.equal(mock.mock.callCount(), 0);
});
test("응답 body를 읽는 중에도 시간 초과 적용", async (t) => {
  t.mock.method(globalThis, "fetch", async (_url, options) => ({
    status:200, headers:new Headers({"Content-Type":"application/json"}),
    json:() => new Promise((_resolve,reject) => {
      options.signal.addEventListener("abort", () => reject(new DOMException("abort","AbortError")), {once:true});
    }),
  }));
  await assert.rejects(askQuestion("질문", signal(), 10), {kind:"timeout"});
});
