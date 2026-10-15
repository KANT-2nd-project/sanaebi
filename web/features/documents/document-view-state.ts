import type { DocumentDetail, DocumentSummary } from "../../lib/api/documents";

export type DocumentView = {
  q: string; status: "all" | "draft" | "published" | "withdrawn"; page: number;
  id: string | null; isNew: boolean; editing: boolean; revision: "draft" | "published" | null;
};
export function parseDocumentView(search: string): DocumentView {
  const params = new URLSearchParams(search);
  const status = params.get("status");
  const page = Number(params.get("page") ?? 1);
  const id = params.get("id") || null;
  const isNew = !id && params.get("new") === "1";
  const revision = params.get("revision");
  return {
    q: (params.get("q") ?? "").slice(0, 200),
    status: status === "draft" || status === "published" || status === "withdrawn" ? status : "all",
    page: Number.isSafeInteger(page) && page > 0 ? page : 1,
    id, isNew, editing: isNew || Boolean(id && params.get("mode") === "edit"),
    revision: revision === "draft" || revision === "published" ? revision : null,
  };
}
export function documentViewUrl(view: DocumentView): string {
  const params = new URLSearchParams();
  if (view.q) params.set("q", view.q);
  if (view.status !== "all") params.set("status", view.status);
  if (view.page > 1) params.set("page", String(view.page));
  if (view.id) {
    params.set("id", view.id);
    if (view.editing) params.set("mode", "edit");
    if (!view.editing && view.revision) params.set("revision", view.revision);
  } else if (view.isNew) params.set("new", "1");
  return `/admin/documents${params.size ? `?${params}` : ""}`;
}
export function selectedRevision(detail: DocumentDetail, revision: DocumentView["revision"]) {
  return revision === "draft" ? detail.draft : detail.published ?? detail.draft;
}
export function hasDraftChanges(detail: DocumentSummary) {
  return Boolean(detail.published && detail.published.id !== detail.draft.id);
}
export function eligibilityLabel(value: DocumentSummary["eligibility"]) {
  return value === "eligible" ? "답변 사용 중" : value === "scheduled" ? "시행일 대기"
    : value === "withdrawn" ? "사용 중단 · 답변 제외" : "초안 · 답변 제외";
}
export function reviewLabel(value?: string) {
  return value === "ai_reviewed" ? "AI 검수" : value === "unreviewed" ? "미검수" : value || "검수 정보 없음";
}

/** The list opens the same revision as the default reader. */
export function listRevision(document: DocumentSummary) {
  return document.published ?? document.draft;
}
