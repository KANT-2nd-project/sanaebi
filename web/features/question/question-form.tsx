"use client";

import { useLayoutEffect, useRef, type FormEventHandler, type RefObject } from "react";

const examples = [
  { label: "휴가 신청 절차", question: "휴가 신청 절차를 알려주세요." },
  { label: "비용 정산 준비", question: "비용 정산에 필요한 자료는 무엇인가요?" },
  { label: "업무용 계정 발급", question: "업무용 계정은 어떻게 발급받나요?" },
];

type QuestionFormProps = {
  question: string;
  error: string;
  pending: boolean;
  empty: boolean;
  touchEnter: boolean;
  inputRef: RefObject<HTMLTextAreaElement | null>;
  registerButtonRef: RefObject<HTMLButtonElement | null>;
  onChange: (value: string) => void;
  onExample: (value: string) => void;
  onRegister: () => void;
  onSubmit: FormEventHandler<HTMLFormElement>;
};

export function QuestionForm({ question, error, pending, empty, touchEnter, inputRef, registerButtonRef, onChange, onExample, onRegister, onSubmit }: QuestionFormProps) {
  const composing = useRef(false);
  useLayoutEffect(() => {
    const input = inputRef.current;
    if (!input) return;
    const resize = () => {
      input.style.height = "auto";
      input.style.height = `${Math.min(200, Math.max(60, input.scrollHeight))}px`;
      input.style.overflowY = input.scrollHeight > 200 ? "auto" : "hidden";
    };
    resize();
    let width = input.getBoundingClientRect().width;
    const observer = new ResizeObserver(() => {
      const nextWidth = input.getBoundingClientRect().width;
      if (nextWidth !== width) { width = nextWidth; resize(); }
    });
    observer.observe(input);
    return () => observer.disconnect();
  }, [question, inputRef]);

  return (
    <>
      <form onSubmit={(event) => {
        if (composing.current) { event.preventDefault(); return; }
        onSubmit(event);
      }} noValidate>
        <div className={`question-composer${error ? " is-invalid" : ""}`}>
          <label htmlFor="question" className="sr-only">메시지</label>
          <textarea
            id="question" ref={inputRef} value={question} rows={2} readOnly={pending}
            onChange={event => onChange(event.target.value)}
            onCompositionStart={() => { composing.current = true; }}
            onCompositionEnd={() => { composing.current = false; }}
            onKeyDown={event => {
              if (event.nativeEvent.isComposing || composing.current || event.nativeEvent.keyCode === 229) return;
              if (event.key !== "Enter" || event.shiftKey || event.ctrlKey || event.altKey || event.metaKey || touchEnter) return;
              event.preventDefault();
              if (!event.repeat && !pending) event.currentTarget.form?.requestSubmit();
            }}
            aria-invalid={Boolean(error)}
            aria-describedby={`question-help chat-disclosure${error ? " question-error" : ""}`}
            placeholder="사내비에게 질문해보세요"
          />
          {error && <p id="question-error" role="alert" className="input-error">{error}</p>}
          <div className="composer-actions">
            <p id="question-help" className="keyboard-help">
              {touchEnter ? "Enter 줄바꿈 · 버튼으로 전송" : "Enter 전송 · Shift+Enter 줄바꿈"}
            </p>
            <button ref={registerButtonRef} type="button" disabled={pending} className="chat-button register-button" onClick={onRegister}>문서로 등록</button>
            <button type="submit" disabled={pending} className="chat-button send-button">
              전송 <span aria-hidden="true">↑</span>
            </button>
          </div>
        </div>
      </form>
      {empty && <div className="question-examples" role="group" aria-label="예시 질문">
        {examples.map(example => <button key={example.label} type="button" className="chat-button example-button"
          disabled={pending} onClick={() => onExample(example.question)}>{example.label}</button>)}
      </div>}
    </>
  );
}
