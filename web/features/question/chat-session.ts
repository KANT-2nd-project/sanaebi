import { askQuestion, QuestionError } from "../../lib/api/questions";
import type { QuestionErrorKind } from "./types";

export type Turn = {
  id: string;
  question: string;
  status: "pending" | "success" | "error";
  answer?: string;
  error?: { kind: QuestionErrorKind; message: string };
};
export type ChatSnapshot = {
  draft: string;
  turns: Turn[];
  activeTurnId: string | null;
  inputError: string;
  announcement: string;
};
export type SendQuestion = (question: string, signal: AbortSignal) => Promise<string>;

const emptySnapshot = (): ChatSnapshot => ({
  draft: "", turns: [], activeTurnId: null, inputError: "", announcement: "",
});

/** Owns one in-memory conversation and its single active request. */
export class ChatSession {
  state = emptySnapshot();
  private initialState = this.state;
  private listeners = new Set<() => void>();
  private active: AbortController | null = null;
  private sequence = 0;

  constructor(private readonly send: SendQuestion = askQuestion) {}

  getSnapshot = () => this.state;
  getServerSnapshot = () => this.initialState;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };

  private publish(next: ChatSnapshot) {
    this.state = next;
    this.listeners.forEach(listener => listener());
  }

  changeDraft(value: string) {
    if (this.active) return;
    this.publish({ ...this.state, draft: value, inputError: "" });
  }

  async submit() {
    if (this.active) return;
    const question = this.state.draft.trim();
    if (!question) {
      this.publish({ ...this.state, inputError: "질문을 입력해주세요", announcement: "" });
      return;
    }
    const failed = [...this.state.turns].reverse().find(turn => turn.status === "error" && turn.question === question);
    await this.run(question, failed?.id);
  }

  async retry(id: string) {
    if (this.active) return;
    const turn = this.state.turns.find(turn => turn.id === id && turn.status === "error");
    if (turn) await this.run(turn.question, id);
  }

  private async run(question: string, existingId?: string) {
    const controller = new AbortController();
    this.active = controller;
    const id = existingId ?? `turn-${++this.sequence}`;
    const clearSubmittedDraft = this.state.draft.trim() === question;
    const turn: Turn = { id, question, status: "pending" };
    this.publish({
      ...this.state,
      turns: existingId ? this.state.turns.map(item => item.id === id ? turn : item) : [...this.state.turns, turn],
      activeTurnId: id, inputError: "", announcement: "답변을 기다리고 있습니다.",
    });
    try {
      const answer = await this.send(question, controller.signal);
      if (this.active !== controller) return;
      this.active = null;
      this.publish({
        ...this.state,
        draft: clearSubmittedDraft ? "" : this.state.draft,
        turns: this.state.turns.map(item => item.id === id ? { ...turn, status: "success", answer } : item),
        activeTurnId: null, announcement: "답변이 도착했습니다.",
      });
    } catch (error) {
      if (this.active !== controller) return;
      this.active = null;
      const failure = error instanceof QuestionError ? error
        : new QuestionError("request", "요청을 처리하지 못했어요. 다시 시도해주세요.");
      this.publish({
        ...this.state,
        turns: this.state.turns.map(item => item.id === id ? {
          ...turn, status: "error", error: { kind: failure.kind, message: failure.message },
        } : item),
        activeTurnId: null,
        inputError: failure.kind === "validation" && clearSubmittedDraft ? failure.message : "",
        announcement: "답변을 받지 못했습니다. 오류 안내를 확인해주세요.",
      });
    }
  }

  reset() {
    this.dispose();
    this.publish({ ...emptySnapshot(), announcement: "새 대화를 시작했습니다." });
  }

  dispose() {
    const previous = this.active;
    this.active = null;
    previous?.abort();
  }
}
