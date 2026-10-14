import type { Turn } from "./chat-session";
import { MessageItem } from "./message-item";

export function MessageList({ turns, pending, onRetry }: { turns: Turn[]; pending: boolean; onRetry: (id: string) => void }) {
  return <ol className="message-list" aria-label="메시지 목록">
    {turns.map(turn => <MessageItem key={turn.id} turn={turn} pending={pending} onRetry={onRetry} />)}
  </ol>;
}
