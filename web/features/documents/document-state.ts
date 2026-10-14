import type { DocumentDetail, DocumentRevision } from "../../lib/api/documents";

export type DocumentForm = {
  title: string;
  body: string;
  source_label: string;
  source_url: string;
  owner_department: string;
  effective_from: string;
};

export type DocumentFormErrors = Partial<Record<keyof DocumentForm, string>>;

export type DocumentWriteAttempt = {
  method: string;
  path: string;
  body: unknown;
  signature: string;
  key: string;
};

export type ReconciledDocument = {
  detail: DocumentDetail;
  form: DocumentForm;
  baselineForm: DocumentForm;
  latestDetail: DocumentDetail | null;
  conflict: boolean;
};

export function emptyDocumentForm(): DocumentForm {
  return {
    title: "",
    body: "",
    source_label: "공통 자료",
    source_url: "",
    owner_department: "",
    effective_from: "",
  };
}

export function formFromRevision(revision: DocumentRevision): DocumentForm {
  return {
    title: revision.title,
    body: revision.body,
    source_label: revision.source_label,
    source_url: revision.source_url ?? "",
    owner_department: revision.owner_department ?? "",
    effective_from: revision.effective_from ?? "",
  };
}

export function isDocumentFormDirty(form: DocumentForm, baselineForm: DocumentForm): boolean {
  return (Object.keys(form) as (keyof DocumentForm)[]).some(key => form[key] !== baselineForm[key]);
}

function isRealIsoDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const [year, month, day] = value.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
}

export function validateDocumentForm(form: DocumentForm): DocumentFormErrors {
  const errors: DocumentFormErrors = {};
  if (!form.title.trim()) errors.title = "제목을 입력해주세요";
  else if (form.title.length > 200) errors.title = "제목은 200자 이내로 입력해주세요";
  if (!form.body.trim()) errors.body = "원문을 입력해주세요";
  else if (form.body.length > 50_000) errors.body = "원문은 50,000자 이내로 입력해주세요";
  if (form.source_label.length > 200) errors.source_label = "출처 이름은 200자 이내로 입력해주세요";
  if (form.owner_department.length > 200) errors.owner_department = "담당 부서는 200자 이내로 입력해주세요";
  if (form.source_url.length > 2_048) errors.source_url = "출처 주소는 2,048자 이내로 입력해주세요";
  else if (form.source_url && !/^https?:\/\//i.test(form.source_url)) {
    errors.source_url = "http:// 또는 https:// 출처 주소를 입력해주세요";
  } else if (form.source_url) {
    try {
      const url = new URL(form.source_url);
      if (!url.hostname || !["http:", "https:"].includes(url.protocol)) {
        errors.source_url = "http:// 또는 https:// 출처 주소를 입력해주세요";
      }
    } catch {
      errors.source_url = "올바른 출처 주소를 입력해주세요";
    }
  }
  if (form.effective_from && !isRealIsoDate(form.effective_from)) {
    errors.effective_from = "실제 날짜를 입력해주세요";
  }
  return errors;
}

export function documentPayload(form: DocumentForm) {
  return {
    title: form.title,
    body: form.body,
    source_label: form.source_label,
    source_url: form.source_url || null,
    owner_department: form.owner_department || null,
    effective_from: form.effective_from || null,
  };
}

function stableJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record).sort().map(key => `${JSON.stringify(key)}:${stableJson(record[key])}`).join(",")}}`;
  }
  return JSON.stringify(value) ?? "undefined";
}

export function nextWriteAttempt(
  previous: DocumentWriteAttempt | null,
  method: string,
  path: string,
  body: unknown,
  makeKey: () => string,
): DocumentWriteAttempt {
  const signature = `${method.toUpperCase()} ${path} ${stableJson(body)}`;
  if (previous?.signature === signature) return previous;
  return { method: method.toUpperCase(), path, body: structuredClone(body), signature, key: makeKey() };
}

export function newIdempotencyKey(): string {
  if (typeof globalThis.crypto?.randomUUID === "function") return globalThis.crypto.randomUUID();
  const bytes = new Uint8Array(16);
  globalThis.crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map(value => value.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function reconcileDocumentDetail(
  current: Omit<ReconciledDocument, "latestDetail" | "conflict">,
  incoming: DocumentDetail,
): ReconciledDocument {
  if (current.detail.id === incoming.id && isDocumentFormDirty(current.form, current.baselineForm)) {
    return { ...current, latestDetail: incoming, conflict: true };
  }
  const form = formFromRevision(incoming.draft);
  return { detail: incoming, form, baselineForm: form, latestDetail: null, conflict: false };
}
