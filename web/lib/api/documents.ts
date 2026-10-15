export type DocumentStatus = "draft" | "published" | "withdrawn";
export type DocumentEligibility = "draft" | "scheduled" | "eligible" | "withdrawn";

export type DocumentRevisionSummary = {
  id: string;
  revision_number: number;
  title: string;
  source_label: string;
  source_url: string | null;
  owner_department: string | null;
  effective_from: string | null;
  content_hash: string;
  created_at: string;
};

export type RevisionMetadata = {
  category: string | null;
  source_version: string | null;
  review_status: string;
  source_ids: string[];
  policy_decision_ids: string[];
};
export type DocumentProvenance = {
  source_namespace: string;
  source_document_id: string;
  source_file_sha256: string;
  row_sha256: string;
  imported_at: string;
};
export type DocumentRevision = DocumentRevisionSummary & { body: string; metadata?: RevisionMetadata };

export type DocumentSummary = {
  id: string;
  record_version: number;
  withdrawn: boolean;
  created_at: string;
  updated_at: string;
  status: DocumentStatus;
  eligibility: DocumentEligibility;
  draft: DocumentRevisionSummary;
  published: DocumentRevisionSummary | null;
};

export type DocumentDetail = Omit<DocumentSummary, "draft" | "published"> & {
  provenance?: DocumentProvenance | null;
  draft: DocumentRevision;
  published: DocumentRevision | null;
};

export type DocumentListResponse = { items: DocumentSummary[]; total: number };
export type DocumentCapabilities = {
  management_mode: "local-demo";
  answer_integration: "echo" | "connected";
};

export type DocumentPayload = {
  title: string;
  body: string;
  source_label: string;
  source_url: string | null;
  owner_department: string | null;
  effective_from: string | null;
};

export type DocumentListFilters = {
  q?: string;
  status?: "all" | DocumentStatus;
  limit?: number;
  offset?: number;
};

export type DocumentRequestOptions = { signal?: AbortSignal; timeoutMs?: number };

export type DocumentApiErrorKind =
  | "network"
  | "timeout"
  | "aborted"
  | "invalid-response"
  | "request"
  | "gateway"
  | "conflict"
  | "validation"
  | "not-found"
  | "permission";

export class DocumentApiError extends Error {
  constructor(
    readonly kind: DocumentApiErrorKind,
    message: string,
    readonly code?: string,
    readonly details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = "DocumentApiError";
  }
}

const DEFAULT_TIMEOUT_MS = 35_000;
const isRecord = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const isString = (value: unknown): value is string => typeof value === "string";
const isNullableString = (value: unknown): value is string | null => value === null || isString(value);
const isPositiveInteger = (value: unknown): value is number => Number.isInteger(value) && Number(value) > 0;
const isNonNegativeInteger = (value: unknown): value is number => Number.isInteger(value) && Number(value) >= 0;

function parseMetadata(value: unknown): RevisionMetadata | undefined {
  if (value === undefined) return undefined;
  if (!isRecord(value) || !isNullableString(value.category) || !isNullableString(value.source_version)
    || !isString(value.review_status) || !Array.isArray(value.source_ids) || !value.source_ids.every(isString)
    || !Array.isArray(value.policy_decision_ids) || !value.policy_decision_ids.every(isString)) throw invalidResponse();
  return { category: value.category, source_version: value.source_version, review_status: value.review_status,
    source_ids: value.source_ids, policy_decision_ids: value.policy_decision_ids };
}

function parseProvenance(value: unknown): DocumentProvenance | null {
  if (value === undefined || value === null) return null;
  if (!isRecord(value) || !isString(value.source_namespace) || !isString(value.source_document_id)
    || !isString(value.source_file_sha256) || !isString(value.row_sha256) || !isString(value.imported_at)) throw invalidResponse();
  return {source_namespace: value.source_namespace, source_document_id: value.source_document_id,
    source_file_sha256: value.source_file_sha256, row_sha256: value.row_sha256, imported_at: value.imported_at};
}

function parseRevision(value: unknown, includesBody: boolean): DocumentRevisionSummary | DocumentRevision {
  if (!isRecord(value)
    || !isString(value.id)
    || !isPositiveInteger(value.revision_number)
    || !isString(value.title)
    || !isString(value.source_label)
    || !isNullableString(value.source_url)
    || !isNullableString(value.owner_department)
    || !isNullableString(value.effective_from)
    || !isString(value.content_hash)
    || !isString(value.created_at)
    || (includesBody && !isString(value.body))) {
    throw invalidResponse();
  }
  const summary: DocumentRevisionSummary = {
    id: value.id,
    revision_number: value.revision_number,
    title: value.title,
    source_label: value.source_label,
    source_url: value.source_url,
    owner_department: value.owner_department,
    effective_from: value.effective_from,
    content_hash: value.content_hash,
    created_at: value.created_at,
  };
  return includesBody ? { ...summary, body: value.body as string, metadata: parseMetadata(value.metadata) } : summary;
}

function parseDocumentSummary(value: unknown): DocumentSummary {
  if (!isRecord(value)
    || !isString(value.id)
    || !isPositiveInteger(value.record_version)
    || typeof value.withdrawn !== "boolean"
    || !isString(value.created_at)
    || !isString(value.updated_at)
    || !["draft", "published", "withdrawn"].includes(String(value.status))
    || !["draft", "scheduled", "eligible", "withdrawn"].includes(String(value.eligibility))) {
    throw invalidResponse();
  }
  const draft = parseRevision(value.draft, false);
  const published = value.published === null ? null : parseRevision(value.published, false);
  return {
    id: value.id,
    record_version: value.record_version,
    withdrawn: value.withdrawn,
    created_at: value.created_at,
    updated_at: value.updated_at,
    status: value.status as DocumentStatus,
    eligibility: value.eligibility as DocumentEligibility,
    draft: draft as DocumentRevisionSummary,
    published: published as DocumentRevisionSummary | null,
  };
}

export function parseDocumentDetail(value: unknown): DocumentDetail {
  if (!isRecord(value)
    || !isString(value.id)
    || !isPositiveInteger(value.record_version)
    || typeof value.withdrawn !== "boolean"
    || !isString(value.created_at)
    || !isString(value.updated_at)
    || !["draft", "published", "withdrawn"].includes(String(value.status))
    || !["draft", "scheduled", "eligible", "withdrawn"].includes(String(value.eligibility))) {
    throw invalidResponse();
  }
  const draft = parseRevision(value.draft, true) as DocumentRevision;
  const published = value.published === null ? null : parseRevision(value.published, true) as DocumentRevision;
  return {
    id: value.id,
    record_version: value.record_version,
    withdrawn: value.withdrawn,
    created_at: value.created_at,
    updated_at: value.updated_at,
    status: value.status as DocumentStatus,
    eligibility: value.eligibility as DocumentEligibility,
    provenance: parseProvenance(value.provenance),
    draft,
    published,
  };
}

function parseList(value: unknown): DocumentListResponse {
  if (!isRecord(value) || !Array.isArray(value.items) || !isNonNegativeInteger(value.total)) throw invalidResponse();
  return { items: value.items.map(parseDocumentSummary), total: value.total };
}

function parseCapabilities(value: unknown): DocumentCapabilities {
  if (!isRecord(value) || value.management_mode !== "local-demo"
    || !["echo", "connected"].includes(String(value.answer_integration))) throw invalidResponse();
  return { management_mode: "local-demo", answer_integration: value.answer_integration as "echo" | "connected" };
}

function invalidResponse(): DocumentApiError {
  return new DocumentApiError("invalid-response", "문서 API 응답을 확인할 수 없습니다.");
}

function parseErrorEnvelope(value: unknown): { code: string; message: string; details?: Record<string, unknown> } | null {
  if (!isRecord(value) || value.ok !== false || !isRecord(value.error)
    || !isString(value.error.code) || !isString(value.error.message)) return null;
  const details = value.error.details;
  if (details !== undefined && !isRecord(details)) return null;
  return { code: value.error.code, message: value.error.message, details: details as Record<string, unknown> | undefined };
}

function safeFailure(status: number): DocumentApiError {
  if (status === 502 || status === 504 || status >= 500) {
    return new DocumentApiError("gateway", "문서 저장소에 연결하지 못했습니다. 입력을 보존했어요.");
  }
  return new DocumentApiError("invalid-response", "문서 API 오류 응답을 확인할 수 없습니다.");
}

async function request<T>(
  path: string,
  init: RequestInit,
  expectedStatus: number | number[],
  parse: (value: unknown) => T,
  options: DocumentRequestOptions = {},
): Promise<T> {
  if (options.signal?.aborted) throw new DocumentApiError("aborted", "요청이 취소되었습니다.");

  const controller = new AbortController();
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  let didTimeout = false;
  const abortFromCaller = () => controller.abort();
  options.signal?.addEventListener("abort", abortFromCaller, { once: true });
  const timer = setTimeout(() => { didTimeout = true; controller.abort(); }, timeoutMs);
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  headers.set("Cache-Control", "no-store");

  let response: Response;
  try {
    response = await fetch(path, { ...init, headers, cache: "no-store", signal: controller.signal });
  } catch (error) {
    clearTimeout(timer);
    options.signal?.removeEventListener("abort", abortFromCaller);
    if (didTimeout) throw new DocumentApiError("timeout", "35초 동안 응답이 없어 요청을 중단했습니다. 입력을 보존했어요.");
    if (options.signal?.aborted || (error instanceof DOMException && error.name === "AbortError")) {
      throw new DocumentApiError("aborted", "요청이 취소되었습니다.");
    }
    throw new DocumentApiError("network", "네트워크 연결을 확인해주세요. 입력을 보존했어요.");
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    clearTimeout(timer);
    options.signal?.removeEventListener("abort", abortFromCaller);
    if (didTimeout) throw new DocumentApiError("timeout", "35초 동안 응답이 없어 요청을 중단했습니다. 입력을 보존했어요.");
    if (!response.ok && response.status >= 500) throw safeFailure(response.status);
    throw invalidResponse();
  }
  if (didTimeout) {
    clearTimeout(timer);
    options.signal?.removeEventListener("abort", abortFromCaller);
    throw new DocumentApiError("timeout", "35초 동안 응답이 없어 요청을 중단했습니다. 입력을 보존했어요.");
  }
  if (options.signal?.aborted) {
    clearTimeout(timer);
    options.signal.removeEventListener("abort", abortFromCaller);
    throw new DocumentApiError("aborted", "요청이 취소되었습니다.");
  }
  clearTimeout(timer);
  options.signal?.removeEventListener("abort", abortFromCaller);

  if (!response.ok) {
    const failure = parseErrorEnvelope(payload);
    if (!failure) throw safeFailure(response.status);
    const kind: DocumentApiErrorKind = response.status === 409 ? "conflict"
      : response.status === 422 ? "validation"
        : response.status === 404 ? "not-found"
          : response.status === 401 || response.status === 403 ? "permission"
          : response.status >= 500 ? "gateway" : "request";
    throw new DocumentApiError(kind, failure.message, failure.code, failure.details);
  }

  const validStatuses = Array.isArray(expectedStatus) ? expectedStatus : [expectedStatus];
  if (!validStatuses.includes(response.status)) throw new DocumentApiError("request", "문서 요청을 완료하지 못했습니다.");
  return parse(payload);
}

export async function getDocumentCapabilities(options: DocumentRequestOptions = {}): Promise<DocumentCapabilities> {
  return request("/api/documents/capabilities", { method: "GET" }, 200, parseCapabilities, options);
}

export async function listDocuments(
  filters: DocumentListFilters = {},
  options: DocumentRequestOptions = {},
): Promise<DocumentListResponse> {
  const params = new URLSearchParams();
  if (filters.q) params.set("q", filters.q);
  if (filters.status && filters.status !== "all") params.set("status", filters.status);
  params.set("limit", String(filters.limit ?? 20));
  params.set("offset", String(filters.offset ?? 0));
  return request(`/api/documents?${params.toString()}`, { method: "GET" }, 200, parseList, options);
}

export async function getDocument(id: string, options: DocumentRequestOptions = {}): Promise<DocumentDetail> {
  return request(`/api/documents/${encodeURIComponent(id)}`, { method: "GET" }, 200, parseDocumentDetail, options);
}

export async function createDocument(
  payload: DocumentPayload,
  idempotencyKey: string,
  options: DocumentRequestOptions = {},
): Promise<DocumentDetail> {
  return request("/api/documents", {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
    body: JSON.stringify(payload),
  }, 201, parseDocumentDetail, options);
}

export async function updateDocument(
  id: string,
  expectedVersion: number,
  payload: DocumentPayload,
  idempotencyKey: string,
  options: DocumentRequestOptions = {},
): Promise<DocumentDetail> {
  return request(`/api/documents/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
    body: JSON.stringify({ expected_version: expectedVersion, ...payload }),
  }, 200, parseDocumentDetail, options);
}

export async function publishDocument(
  id: string,
  expectedVersion: number,
  revisionId: string,
  idempotencyKey: string,
  options: DocumentRequestOptions = {},
): Promise<DocumentDetail> {
  return request(`/api/documents/${encodeURIComponent(id)}/publish`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
    body: JSON.stringify({ expected_version: expectedVersion, revision_id: revisionId }),
  }, 200, parseDocumentDetail, options);
}

export async function withdrawDocument(
  id: string,
  expectedVersion: number,
  idempotencyKey: string,
  options: DocumentRequestOptions = {},
): Promise<DocumentDetail> {
  return request(`/api/documents/${encodeURIComponent(id)}/withdraw`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
    body: JSON.stringify({ expected_version: expectedVersion }),
  }, 200, parseDocumentDetail, options);
}

export type MaintenanceAction = "clear" | "restore";
export type MaintenancePreview = { action: MaintenanceAction; total_count: number; restored_count: number; expected_state: string };
export type MaintenanceResult = { action: MaintenanceAction; deleted_count: number; restored_count: number; completed_at: string };

function parseMaintenancePreview(value: unknown): MaintenancePreview {
  if (!isRecord(value) || !["clear", "restore"].includes(String(value.action)) || !isNonNegativeInteger(value.total_count)
    || !isNonNegativeInteger(value.restored_count) || !isString(value.expected_state) || !/^[0-9a-f]{64}$/.test(value.expected_state)) throw invalidResponse();
  return value as MaintenancePreview;
}
function parseMaintenanceResult(value: unknown): MaintenanceResult {
  if (!isRecord(value) || !["clear", "restore"].includes(String(value.action)) || !isNonNegativeInteger(value.deleted_count)
    || !isNonNegativeInteger(value.restored_count) || !isString(value.completed_at)) throw invalidResponse();
  return value as MaintenanceResult;
}
export function previewDocumentMaintenance(action: MaintenanceAction, options: DocumentRequestOptions = {}) {
  return request(`/api/documents/maintenance-preview?action=${action}`, { method: "GET" }, 200, parseMaintenancePreview, options);
}
export function maintainDocuments(preview: MaintenancePreview, key: string) {
  return request("/api/documents/maintenance", { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": key },
    body: JSON.stringify({ action: preview.action, expected_state: preview.expected_state }) }, 200, parseMaintenanceResult, {});
}
