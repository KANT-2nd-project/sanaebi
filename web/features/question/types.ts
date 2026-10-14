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
