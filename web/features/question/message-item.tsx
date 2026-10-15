import { MarkdownContent } from "../../components/markdown-content";
import type { Turn } from "./chat-session";

export function MessageItem({ turn, pending, onRetry }: { turn: Turn; pending: boolean; onRetry: (id: string) => void }) {
  return (
    <li className="chat-turn" data-turn-id={turn.id}>
      <div className="user-message" aria-label="사용자 메시지">{turn.question}</div>
      <section className="assistant-message" aria-labelledby={`${turn.id}-label`}>
        <h2 id={`${turn.id}-label`} className="message-author">사내비</h2>
        {turn.status === "pending" && <p className="pending-message">답변을 기다리고 있습니다.</p>}
        {turn.status === "success" && <div className="answer-text"><MarkdownContent text={turn.answer ?? ""} /></div>}
        {turn.status === "error" && <div className="message-error">
          <h3>답변을 받지 못했어요</h3>
          <p>{turn.error?.message}</p>
          <button type="button" disabled={pending} className="chat-button retry-button" onClick={() => onRetry(turn.id)}
            aria-label={`다시 시도: ${turn.question}`}>다시 시도</button>
        </div>}
      </section>
    </li>
  );
}
