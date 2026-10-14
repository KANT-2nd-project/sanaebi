type AnswerCardProps = {
  text: string;
  question: string;
};

export function AnswerCard({ text, question }: AnswerCardProps) {
  return (
    <section aria-labelledby="answer-title" className="mt-8 border-t border-boundary pt-6">
      <h2 id="answer-title" className="text-xl font-semibold">답변</h2>
      <p className="mt-3 whitespace-pre-wrap [overflow-wrap:anywhere] text-sm text-muted">질문: {question}</p>
      <p className="mt-3 whitespace-pre-wrap [overflow-wrap:anywhere] text-muted">
        {text}
      </p>
    </section>
  );
}
