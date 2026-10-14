export type AnswerResponse = {
  ok: boolean;
  text: string;
  reason: string;
};

export type QuestionErrorKind =
  | "validation"
  | "generation"
  | "gateway"
  | "invalid-response"
  | "request"
  | "network"
  | "timeout"
  | "aborted";

export type QuestionState =
  | { status: "idle" }
  | { status: "submitting"; submittedQuestion: string }
  | { status: "success"; submittedQuestion: string; answer: string }
  | { status: "error"; kind: QuestionErrorKind; message: string };
