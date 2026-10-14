"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { askQuestion, QuestionError } from "@/lib/api/questions";
import { AnswerCard } from "./answer-card";
import { QuestionForm } from "./question-form";
import type { QuestionState } from "./types";

export function QuestionPanel() {
  const [question, setQuestion] = useState("");
  const [inputError, setInputError] = useState("");
  const [state, setState] = useState<QuestionState>({ status: "idle" });
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const activeRequest = useRef<AbortController | null>(null);

  useEffect(() => () => {
    activeRequest.current?.abort();
    activeRequest.current = null;
  }, []);

  function changeQuestion(value: string) {
    if (activeRequest.current) return;
    setQuestion(value);
    setInputError("");
    setState({ status: "idle" });
  }

  async function submitQuestion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (activeRequest.current) return;
    const submittedQuestion = question.trim();
    if (!submittedQuestion) {
      setState({ status: "idle" });
      setInputError("질문을 입력해주세요");
      inputRef.current?.focus();
      return;
    }
    const controller = new AbortController();
    activeRequest.current = controller;
    setInputError("");
    setState({ status: "submitting", submittedQuestion });
    try {
      const answer = await askQuestion(submittedQuestion, controller.signal);
      if (activeRequest.current !== controller) return;
      setState({ status: "success", submittedQuestion, answer });
    } catch (error) {
      if (activeRequest.current !== controller || controller.signal.aborted) return;
      const failure = error instanceof QuestionError
        ? error
        : new QuestionError("request", "요청을 처리하지 못했어요. 다시 시도해주세요.");
      setState({ status: "error", kind: failure.kind, message: failure.message });
      if (failure.kind === "validation") {
        setInputError(failure.message);
        inputRef.current?.focus();
      }
    } finally {
      if (activeRequest.current === controller) activeRequest.current = null;
    }
  }

  const pending = state.status === "submitting";
  const statusMessage = pending ? "답변을 준비하고 있어요"
    : state.status === "success" ? "답변이 도착했습니다."
    : state.status === "error" ? "요청을 완료하지 못했습니다. 오류 안내를 확인해주세요." : "";

  return (
    <div className="mt-8">
      <div aria-busy={pending}>
        <QuestionForm
          question={question}
          error={inputError}
          pending={pending}
          inputRef={inputRef}
          onChange={changeQuestion}
          onExample={(value) => {
            changeQuestion(value);
            inputRef.current?.focus();
          }}
          onSubmit={submitQuestion}
        />
        {state.status === "success" && (
          <AnswerCard text={state.answer} question={state.submittedQuestion} />
        )}
        {state.status === "error" && state.kind !== "validation" && (
          <section aria-labelledby="error-title" className="mt-8 border-t border-boundary pt-6">
            <h2 id="error-title" className="text-xl font-semibold text-danger">답변을 받지 못했어요</h2>
            <p className="mt-3 whitespace-pre-wrap [overflow-wrap:anywhere]">{state.message}</p>
            <p className="mt-2 text-sm text-muted">입력한 질문을 확인한 후 질문하기를 눌러 다시 시도해주세요.</p>
          </section>
        )}
      </div>
      <p role="status" className={pending ? "mt-4 text-muted" : "sr-only"}>{statusMessage}</p>
    </div>
  );
}
