import type { AnswerResponse, QuestionErrorKind } from "../../features/question/types";

export const QUESTION_TIMEOUT_MS = 240_000;

export class QuestionError extends Error {
  constructor(public readonly kind: QuestionErrorKind, message: string) {
    super(message);
    this.name = "QuestionError";
  }
}

function isAnswerResponse(value: unknown): value is AnswerResponse {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  return typeof record.ok === "boolean" &&
    typeof record.text === "string" && typeof record.reason === "string";
}

function invalidResponse(): QuestionError {
  return new QuestionError("invalid-response", "응답을 확인하지 못했어요. 잠시 후 다시 시도해주세요.");
}

export async function askQuestion(
  question: string,
  signal: AbortSignal,
  timeoutMs = QUESTION_TIMEOUT_MS,
): Promise<string> {
  const controller = new AbortController();
  let timedOut = false;
  const cancel = () => controller.abort();
  signal.addEventListener("abort", cancel, { once: true });
  if (signal.aborted) cancel();
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  try {
    if (signal.aborted) throw new QuestionError("aborted", "요청이 취소되었습니다.");
    const response = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
      cache: "no-store",
      signal: controller.signal,
    });
    const mediaType = response.headers.get("Content-Type")?.split(";")[0].trim().toLowerCase();
    if (mediaType !== "application/json") {
      if (response.status === 502 || response.status === 504) {
        throw new QuestionError("gateway", "답변 서버에 연결하지 못했어요. 잠시 후 다시 시도해주세요.");
      }
      throw invalidResponse();
    }
    let value: unknown;
    try {
      value = await response.json();
    } catch {
      throw invalidResponse();
    }
    if (signal.aborted || timedOut) throw invalidResponse();
    if (![200, 422, 429, 502, 503].includes(response.status)) {
      throw new QuestionError("request", "요청을 처리하지 못했어요. 잠시 후 다시 시도해주세요.");
    }
    if (!isAnswerResponse(value)) throw invalidResponse();
    if (response.status === 200 && value.ok && value.text.trim()) return value.text;
    if ((response.status === 422 || response.status === 429 || response.status === 502 || response.status === 503) &&
        !value.ok && value.text === "" && value.reason.trim()) {
      const kind = response.status === 422 ? "validation"
        : response.status === 429 ? "rate-limit"
          : response.status === 502 ? "generation" : "unavailable";
      throw new QuestionError(kind, value.reason);
    }
    throw invalidResponse();
  } catch (error) {
    if (signal.aborted) throw new QuestionError("aborted", "요청이 취소되었습니다.");
    if (timedOut) throw new QuestionError("timeout", "답변 대기 시간이 초과되었어요. 잠시 후 다시 시도해주세요.");
    if (error instanceof QuestionError) throw error;
    throw new QuestionError("network", "연결을 확인해주세요. 질문을 수정하거나 다시 시도할 수 있습니다.");
  } finally {
    clearTimeout(timer);
    signal.removeEventListener("abort", cancel);
  }
}
