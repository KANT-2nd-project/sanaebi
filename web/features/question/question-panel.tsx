"use client";

import Link from "next/link";
import { useEffect, useRef, useState, useSyncExternalStore, type FormEvent } from "react";
import { ChatSession } from "./chat-session";
import { MessageList } from "./message-list";
import { QuestionForm } from "./question-form";
import { useChatScroll } from "./use-chat-scroll";

const touchQuery = "(hover: none) and (pointer: coarse)";
const subscribeTouch = (notify: () => void) => {
  const query = window.matchMedia(touchQuery);
  query.addEventListener("change", notify);
  return () => query.removeEventListener("change", notify);
};

export function QuestionPanel() {
  const [session] = useState(() => new ChatSession());
  const state = useSyncExternalStore(session.subscribe, session.getSnapshot, session.getServerSnapshot);
  const touchEnter = useSyncExternalStore(subscribeTouch, () => window.matchMedia(touchQuery).matches, () => false);
  const [showGuide, setShowGuide] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const guideRef = useRef<HTMLElement>(null);
  const { viewportRef, dockRef, onScroll, showLatest, toLatest } = useChatScroll(state.turns);
  const pending = state.activeTurnId !== null;
  const empty = state.turns.length === 0;

  useEffect(() => () => session.dispose(), [session]);
  useEffect(() => { if (state.inputError) inputRef.current?.focus(); }, [state.inputError]);
  useEffect(() => { if (showGuide) guideRef.current?.scrollIntoView({ block: "nearest" }); }, [showGuide]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void session.submit();
  }

  return (
    <div className={`chat-shell${empty ? " is-empty" : ""}`}>
      <header className="chat-header">
        <Link href="/" className="chat-brand">사내<span>비</span></Link>
        <nav aria-label="대화 메뉴">
          <button type="button" className="chat-button header-button" disabled={empty && !state.draft}
            onClick={() => { session.reset(); inputRef.current?.focus(); }}>새 대화</button>
          <button type="button" className="chat-button header-button" aria-expanded={showGuide} aria-controls="usage"
            onClick={() => setShowGuide(value => !value)}>사용 안내</button>
        </nav>
      </header>
      <main ref={viewportRef} onScroll={onScroll} className="chat-viewport" aria-label="대화 내용" tabIndex={0}>
        {empty ? <section className="chat-welcome">
          <p className="chat-eyebrow">회사 생활의 작은 길잡이</p>
          <h1>무엇을 도와드릴까요?</h1>
          <p>회사 규정과 업무 절차에 대해 질문해보세요.</p>
        </section> : <h1 className="sr-only">사내비와 대화</h1>}
        <section ref={guideRef} id="usage" className="chat-guide" hidden={!showGuide} aria-labelledby="usage-title">
          <h2 id="usage-title">사용 안내</h2>
          <p>현재는 입력한 질문을 그대로 반환하는 연결 확인 단계입니다. 실제 규정 답변은 아직 제공하지 않습니다.</p>
          <p>화면의 이전 메시지는 답변에 반영되지 않습니다. 대상과 상황을 함께 적어주세요.</p>
          <p>대화는 현재 화면에서만 유지되며 새로고침·새 대화 시 초기화됩니다. 실제 신청·승인·개인 기록 조회는 지원하지 않습니다.</p>
        </section>
        <MessageList turns={state.turns} pending={pending} onRetry={id => { void session.retry(id); }} />
      </main>
      <div className="chat-dock" ref={dockRef}>
        <div className="chat-dock-inner">
          {showLatest && <button type="button" className="chat-button latest-button" onClick={toLatest}>최신 메시지로 이동 ↓</button>}
          <QuestionForm question={state.draft} error={state.inputError} pending={pending} empty={empty}
            touchEnter={touchEnter} inputRef={inputRef} onChange={value => session.changeDraft(value)}
            onExample={value => { session.changeDraft(value); inputRef.current?.focus(); }} onSubmit={submit} />
          <p id="chat-disclosure" className="chat-disclosure">현재는 질문을 그대로 반환합니다. 이전 메시지는 답변에 반영되지 않으며 새로고침하면 대화가 초기화됩니다.</p>
          <p role="status" className="sr-only">{state.announcement}</p>
        </div>
      </div>
    </div>
  );
}
