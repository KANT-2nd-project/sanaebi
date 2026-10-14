import type { FormEventHandler, RefObject } from "react";

const examples = [
  { label: "휴가 신청 절차", question: "휴가 신청 절차를 알려주세요." },
  { label: "비용 정산 준비", question: "비용 정산에 필요한 자료는 무엇인가요?" },
  { label: "업무용 계정 발급", question: "업무용 계정은 어떻게 발급받나요?" },
];

type QuestionFormProps = {
  question: string;
  error: string;
  pending: boolean;
  inputRef: RefObject<HTMLTextAreaElement | null>;
  onChange: (value: string) => void;
  onExample: (value: string) => void;
  onSubmit: FormEventHandler<HTMLFormElement>;
};

export function QuestionForm({ question, error, pending, inputRef, onChange, onExample, onSubmit }: QuestionFormProps) {
  return (
    <form onSubmit={onSubmit} noValidate>
      <div className="rounded-xl border border-boundary bg-surface p-4 sm:p-5">
        <label htmlFor="question" className="font-semibold">질문</label>
        <textarea
          id="question"
          ref={inputRef}
          value={question}
          onChange={(event) => onChange(event.target.value)}
          rows={4}
          readOnly={pending}
          aria-invalid={Boolean(error)}
          aria-describedby={`question-help${error ? " question-error" : ""}`}
          placeholder="예: 휴가를 신청하려면 어떤 절차가 필요한가요?"
          className="mt-3 block w-full resize-y rounded-sm bg-surface text-base leading-[1.7] placeholder:text-muted"
        />
        {error && <p id="question-error" role="alert" className="mt-3 text-danger">{error}</p>}
        <div className="mt-4 flex flex-wrap items-end justify-between gap-4">
          <p id="question-help" className="text-sm text-muted">
            Enter는 줄바꿈입니다.<br />
            이전 대화를 참조하지 않으므로<br />
            대상과 질문을 함께 적어주세요.
          </p>
          <button disabled={pending} type="submit" className="min-h-12 rounded-lg disabled:cursor-wait disabled:opacity-60 bg-action px-5 py-3 font-medium text-white">
            질문하기
          </button>
        </div>
      </div>
      <p id="examples-title" className="mt-6 text-sm text-muted">이런 질문을 해보세요</p>
      <div aria-labelledby="examples-title" role="group" className="mt-3 flex flex-wrap gap-2">
        {examples.map((example) => (
          <button key={example.label} type="button" disabled={pending} onClick={() => onExample(example.question)} className="min-h-12 rounded-lg border border-boundary bg-surface disabled:opacity-60 px-4 py-2 text-sm">
            {example.label}
          </button>
        ))}
      </div>
    </form>
  );
}
