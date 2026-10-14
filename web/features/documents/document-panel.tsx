"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import {
  createDocument, DocumentApiError, getDocument, getDocumentCapabilities, listDocuments,
  publishDocument, updateDocument, withdrawDocument,
  type DocumentCapabilities, type DocumentDetail, type DocumentListResponse, type DocumentPayload,
  type DocumentStatus, type DocumentSummary,
} from "../../lib/api/documents";
import {
  documentPayload, emptyDocumentForm, formFromRevision, isDocumentFormDirty,
  newIdempotencyKey, nextWriteAttempt, validateDocumentForm,
  type DocumentForm, type DocumentFormErrors, type DocumentWriteAttempt,
} from "./document-state";
import { DocumentRouteState } from "./document-route-state";
import { DocumentActionDialog, type DocumentAction } from "./document-action-dialog";
import { DocumentEditor } from "./document-editor";

const PAGE_SIZE = 20;
type WriteKind = "save" | "publish" | "withdraw";
type PendingWrite = { kind: WriteKind; attempt: DocumentWriteAttempt; documentId: string | null; originRoute: string };
type ListFilters = { q: string; status: "all" | DocumentStatus; offset: number };

function errorMessage(error: unknown, fallback: string): { message: string; kind: DocumentApiError["kind"] | "" } {
  if (!(error instanceof DocumentApiError)) return { message: fallback, kind: "" };
  if (error.kind === "permission") return { message: "이 문서 관리 화면을 볼 권한이 없습니다.", kind: error.kind };
  if (error.kind === "not-found") return { message: "문서를 찾을 수 없습니다. 목록을 새로고침해주세요.", kind: error.kind };
  return { message: error.message, kind: error.kind };
}

function statusLabel(status: DocumentStatus): string {
  return status === "published" ? "게시됨" : status === "withdrawn" ? "사용 중단" : "초안";
}

function eligibilityLabel(value: DocumentSummary["eligibility"]): string {
  return value === "eligible" ? "현재 답변 대상" : value === "scheduled" ? "시행일 대기"
    : value === "withdrawn" ? "답변 제외" : "초안 · 답변 제외";
}

function dateLabel(value: string | null | undefined): string {
  if (!value) return "미지정";
  const date = value.slice(0, 10);
  return /^\d{4}-\d{2}-\d{2}$/.test(date) ? date : value;
}

function isTransient(kind: string) {
  return ["timeout", "network", "gateway"].includes(kind);
}

export function DocumentPanel() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const search = searchParams?.toString() ?? "";
  const selectedId = searchParams?.get("id") ?? null;
  const isNew = searchParams?.get("new") === "1";
  const editorOpen = Boolean(selectedId || isNew);
  const routeUrl = `${pathname ?? "/admin/documents"}${search ? `?${search}` : ""}`;
  const [routeState] = useState(() => new DocumentRouteState(routeUrl));

  const [capabilities, setCapabilities] = useState<DocumentCapabilities | null>(null);
  const [capabilityError, setCapabilityError] = useState("");
  const [filters, setFilters] = useState<ListFilters>({ q: "", status: "all", offset: 0 });
  const [searchInput, setSearchInput] = useState("");
  const [list, setList] = useState<DocumentListResponse | null>(null);
  const [listBusy, setListBusy] = useState(true);
  const [listError, setListError] = useState("");
  const [listErrorKind, setListErrorKind] = useState("");
  const [listRefresh, setListRefresh] = useState(0);

  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  const [detailBusy, setDetailBusy] = useState(false);
  const [form, setForm] = useState<DocumentForm>(() => emptyDocumentForm());
  const [baselineForm, setBaselineForm] = useState<DocumentForm>(() => emptyDocumentForm());
  const [formErrors, setFormErrors] = useState<DocumentFormErrors>({});
  const [latestConflict, setLatestConflict] = useState<DocumentDetail | null>(null);
  const [writeFailure, setWriteFailure] = useState("");
  const [writeFailureKind, setWriteFailureKind] = useState("");
  const [writePending, setWritePending] = useState(false);
  const [notice, setNotice] = useState("");
  const [pendingWrite, setPendingWrite] = useState<PendingWrite | null>(null);
  const [actionDialog, setActionDialog] = useState<DocumentAction | null>(null);
  const [actionBusy, setActionBusy] = useState(false);

  const editorFormRef = useRef<HTMLFormElement>(null);
  const requestInFlight = useRef(false);
  const pendingWriteRef = useRef<PendingWrite | null>(null);
  const loadedResourceKey = useRef<string | null>(null);
  const dirtyRef = useRef(false);
  const resourceKey = selectedId ? `document:${selectedId}` : isNew ? "new-document" : "document-list";
  const editorDirty = editorOpen && isDocumentFormDirty(form, baselineForm);
  useEffect(() => { dirtyRef.current = editorDirty; }, [editorDirty]);

  const setCurrentWrite = useCallback((value: PendingWrite | null) => {
    pendingWriteRef.current = value;
    setPendingWrite(value);
  }, []);

  function mayDiscard() {
    if (requestInFlight.current) {
      setWriteFailure("저장 작업이 진행 중입니다. 완료 결과를 확인한 뒤 이동해주세요.");
      return false;
    }
    if (!dirtyRef.current && !pendingWriteRef.current) return true;
    return window.confirm("저장하지 않은 문서 내용이나 확인이 필요한 요청이 있습니다. 이동하면 내용이 사라질 수 있습니다. 계속할까요?");
  }

  function navigate(path: string, replace = false) {
    if (!mayDiscard()) return;
    routeState.approve(path);
    if (replace) router.replace(path);
    else router.push(path);
  }

  const handleRouteChange = useCallback((url: string) => {
    const transition = routeState.observe(url, {
      dirty: dirtyRef.current,
      pendingWrite: requestInFlight.current,
      confirmDiscard: () => window.confirm("저장하지 않은 문서 내용이 사라질 수 있습니다. 이동할까요?"),
    });
    if (transition.kind === "blocked") router.replace(transition.restoreUrl);
  }, [routeState, router]);

  useEffect(() => {
    handleRouteChange(routeUrl);
  }, [handleRouteChange, routeUrl]);

  useEffect(() => {
    const onPopState = () => handleRouteChange(`${window.location.pathname}${window.location.search}`);
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [handleRouteChange]);

  useEffect(() => {
    if (!editorDirty && !pendingWrite) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [editorDirty, pendingWrite]);

  useEffect(() => {
    const controller = new AbortController();
    getDocumentCapabilities({ signal: controller.signal }).then(setCapabilities).catch(error => {
      if (error instanceof DocumentApiError && error.kind === "aborted") return;
      setCapabilityError(errorMessage(error, "관리 기능 상태를 불러오지 못했습니다.").message);
    });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    listDocuments({ q: filters.q, status: filters.status, limit: PAGE_SIZE, offset: filters.offset }, { signal: controller.signal })
      .then(result => { setList(result); setListBusy(false); })
      .catch(error => {
        if (error instanceof DocumentApiError && error.kind === "aborted") return;
        const issue = errorMessage(error, "문서 목록을 불러오지 못했습니다.");
        setListError(issue.message);
        setListErrorKind(issue.kind);
        setList(null);
        setListBusy(false);
      });
    return () => controller.abort();
  }, [filters, listRefresh]);

  // Keep the editor draft aligned with the static route's client-side query state.
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (!routeState.canLoad(routeUrl) || loadedResourceKey.current === resourceKey) return;
    if (isNew) {
      loadedResourceKey.current = resourceKey;
      const empty = emptyDocumentForm();
      setDetail(null);
      setDetailBusy(false);
      setForm(empty);
      setBaselineForm(empty);
      setFormErrors({});
      setLatestConflict(null);
      setWriteFailure("");
      setWriteFailureKind("");
      setNotice("");
      setCurrentWrite(null);
      return;
    }
    if (!selectedId) {
      loadedResourceKey.current = resourceKey;
      setDetail(null);
      setDetailBusy(false);
      return;
    }
    const controller = new AbortController();
    setDetailBusy(true);
    setWriteFailure("");
    getDocument(selectedId, { signal: controller.signal }).then(result => {
      if (controller.signal.aborted) return;
      const nextForm = formFromRevision(result.draft);
      setDetail(result);
      setForm(nextForm);
      setBaselineForm(nextForm);
      setFormErrors({});
      setLatestConflict(null);
      setCurrentWrite(null);
      loadedResourceKey.current = resourceKey;
      setDetailBusy(false);
    }).catch(error => {
      if (error instanceof DocumentApiError && error.kind === "aborted") return;
      const issue = errorMessage(error, "문서 내용을 불러오지 못했습니다.");
      setWriteFailure(issue.message);
      setWriteFailureKind(issue.kind);
      setDetail(null);
      setDetailBusy(false);
    });
    return () => controller.abort();
  }, [selectedId, isNew, resourceKey, routeState, routeUrl, setCurrentWrite]);
  /* eslint-enable react-hooks/set-state-in-effect */

  async function refreshList() {
    setListBusy(true);
    setListError("");
    setListRefresh(value => value + 1);
  }

  function editField(field: keyof DocumentForm, value: string) {
    setForm(current => ({ ...current, [field]: value }));
    setFormErrors(current => ({ ...current, [field]: undefined }));
    setWriteFailure("");
    setWriteFailureKind("");
    setCurrentWrite(null);
    setNotice("");
  }

  async function fetchLatestConflict(documentId: string) {
    try {
      const current = await getDocument(documentId);
      setLatestConflict(current);
    } catch {
      setWriteFailure(current => `${current} 최신 문서도 확인하지 못했습니다. 다시 불러오기를 눌러주세요.`);
    }
  }

  async function executeWrite(pending: PendingWrite) {
    if (requestInFlight.current) return;
    requestInFlight.current = true;
    setWritePending(true);
    setWriteFailure("");
    setWriteFailureKind("");
    setNotice("");
    setActionBusy(pending.kind !== "save");
    try {
      const body = pending.attempt.body as Record<string, unknown>;
      let result: DocumentDetail;
      if (pending.kind === "save" && pending.attempt.method === "POST") {
        result = await createDocument(body as unknown as DocumentPayload, pending.attempt.key);
      } else if (pending.kind === "save") {
        const { expected_version: expectedVersion, ...payload } = body;
        result = await updateDocument(
          pending.documentId!, Number(expectedVersion), payload as unknown as DocumentPayload, pending.attempt.key,
        );
      } else if (pending.kind === "publish") {
        result = await publishDocument(
          pending.documentId!, Number(body.expected_version), String(body.revision_id), pending.attempt.key,
        );
      } else {
        result = await withdrawDocument(pending.documentId!, Number(body.expected_version), pending.attempt.key);
      }
      if (!routeState.canLoad(pending.originRoute)) {
        setCurrentWrite(null);
        void refreshList();
        return;
      }
      const nextForm = formFromRevision(result.draft);
      setDetail(result);
      setForm(nextForm);
      setBaselineForm(nextForm);
      setCurrentWrite(null);
      setLatestConflict(null);
      setFormErrors({});
      setNotice(pending.kind === "publish" ? "문서를 답변 대상으로 지정했습니다."
        : pending.kind === "withdraw" ? "문서를 사용 중단했습니다." : "초안을 저장했습니다.");
      setActionDialog(null);
      if (pending.kind === "save" && pending.attempt.method === "POST") {
        const path = `/admin/documents?id=${encodeURIComponent(result.id)}`;
        routeState.approve(path);
        router.replace(path);
      }
      void refreshList();
    } catch (error) {
      if (!routeState.canLoad(pending.originRoute)) {
        setCurrentWrite(null);
        void refreshList();
        return;
      }
      const issue = errorMessage(error, "문서 변경을 완료하지 못했습니다. 입력은 보존했습니다.");
      setWriteFailure(issue.message);
      setWriteFailureKind(issue.kind);
      setActionDialog(null);
      if (issue.kind === "conflict" && pending.documentId) void fetchLatestConflict(pending.documentId);
    } finally {
      requestInFlight.current = false;
      setWritePending(false);
      setActionBusy(false);
    }
  }

  function beginWrite(kind: WriteKind, method: string, path: string, body: unknown) {
    if (requestInFlight.current) return;
    const previous = pendingWriteRef.current?.attempt ?? null;
    const attempt = nextWriteAttempt(previous, method, path, body, newIdempotencyKey);
    const pending: PendingWrite = { kind, attempt, documentId: detail?.id ?? null, originRoute: routeUrl };
    setCurrentWrite(pending);
    void executeWrite(pending);
  }

  function saveDraft(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    if (writePending) return;
    const nextErrors = validateDocumentForm(form);
    setFormErrors(nextErrors);
    if (Object.keys(nextErrors).length) {
      queueMicrotask(() => editorFormRef.current?.querySelector<HTMLElement>("[aria-invalid='true']")?.focus());
      return;
    }
    const payload = documentPayload(form);
    if (!detail) {
      beginWrite("save", "POST", "/api/documents", payload);
    } else {
      beginWrite("save", "PATCH", `/api/documents/${detail.id}`, {
        expected_version: detail.record_version,
        ...payload,
      });
    }
  }

  function openAction(action: DocumentAction) {
    if (!detail || editorDirty || writePending) return;
    setActionDialog(action);
  }

  function confirmAction() {
    if (!detail || !actionDialog || writePending) return;
    if (actionDialog === "publish") {
      beginWrite("publish", "POST", `/api/documents/${detail.id}/publish`, {
        expected_version: detail.record_version,
        revision_id: detail.draft.id,
      });
    } else {
      beginWrite("withdraw", "POST", `/api/documents/${detail.id}/withdraw`, {
        expected_version: detail.record_version,
      });
    }
  }

  function acceptLatest() {
    if (!latestConflict) return;
    if (editorDirty && !window.confirm("최신 문서로 바꾸면 지금 작성 중인 내용이 사라집니다. 계속할까요?")) return;
    const nextForm = formFromRevision(latestConflict.draft);
    setDetail(latestConflict);
    setForm(nextForm);
    setBaselineForm(nextForm);
    setLatestConflict(null);
    setCurrentWrite(null);
    setWriteFailure("");
    setWriteFailureKind("");
    setNotice("최신 초안을 불러왔습니다. 필요한 내용을 다시 확인해주세요.");
  }

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setListBusy(true);
    setListError("");
    setFilters(current => ({ ...current, q: searchInput, offset: 0 }));
  }

  function openNewDocument() {
    navigate("/admin/documents?new=1");
  }

  const pageNumber = Math.floor(filters.offset / PAGE_SIZE) + 1;
  const totalPages = Math.max(1, Math.ceil((list?.total ?? 0) / PAGE_SIZE));
  const answerIntegration = capabilities?.answer_integration ?? "echo";
  const effectiveFrom = detail?.draft.effective_from ?? null;
  const retryableWrite = pendingWrite && isTransient(writeFailureKind) ? pendingWrite : null;

  return (
    <main className="documents-page">
      <header className="documents-header">
        <Link href="/" className="documents-brand" onClick={event => {
          if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
          event.preventDefault(); navigate("/");
        }}>사내<span>비</span></Link>
        <nav aria-label="문서 관리 메뉴">
          <Link href="/chat" className="documents-nav-link" onClick={event => {
            if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
            event.preventDefault(); navigate("/chat");
          }}>채팅으로 돌아가기</Link>
          <button type="button" className="documents-button documents-button-primary" disabled={writePending} onClick={openNewDocument}>새 문서 초안</button>
        </nav>
      </header>

      <section className="documents-intro" aria-labelledby="documents-title">
        <p className="documents-eyebrow">문서 관리 · {capabilities?.management_mode ?? "local-demo"}</p>
        <h1 id="documents-title">문서를 검토하고 답변 대상을 관리합니다.</h1>
        <p>초안 저장과 게시를 구분합니다. 원문과 메타데이터를 확인한 뒤 게시하세요.</p>
      </section>

      {capabilities?.answer_integration === "echo" && <p className="documents-callout" role="status">
        문서는 저장·관리할 수 있습니다. 현재 채팅은 연결 확인용이며 등록 문서를 사용하지 않습니다.
      </p>}
      {capabilityError && <p className="documents-callout documents-callout-warning" role="status">
        {capabilityError} 채팅의 문서 연결 상태를 확인할 수 없습니다.
      </p>}

      {editorOpen ? (
        <section className="documents-editor-panel" aria-labelledby="document-editor-title">
          <div className="documents-editor-toolbar">
            <button type="button" className="documents-text-button" disabled={writePending} onClick={() => navigate("/admin/documents")}>← 목록</button>
            <span>{detail ? `문서 ID ${detail.id}` : isNew ? "새 문서" : "문서"}</span>
          </div>
          {detailBusy ? <p className="documents-loading" role="status">문서를 불러오는 중…</p> : detail || isNew ? <>
            <div className="documents-editor-heading">
              <div>
                <p className="documents-eyebrow">{detail ? `문서 상태 · ${statusLabel(detail.status)}` : "새 초안"}</p>
                <h2 id="document-editor-title">{detail ? detail.draft.title : "문서 원문 등록"}</h2>
              </div>
              {detail && <span className={`documents-status documents-status-${detail.status}`}>{statusLabel(detail.status)}</span>}
            </div>

            {detail && <div className="documents-version-info" aria-label="문서 버전 정보">
              {detail.published ? <p>현재 게시본 revision {detail.published.revision_number} · 시행일 {dateLabel(detail.published.effective_from)}</p>
                : <p>게시된 revision 없음 · 현재 초안은 답변 대상이 아닙니다.</p>}
              {detail.published && detail.published.id !== detail.draft.id && <p>수정 초안 revision {detail.draft.revision_number}을 저장해도 기존 게시본은 유지됩니다.</p>}
              {detail.status === "published" && <p>게시본 상태: {eligibilityLabel(detail.eligibility)}</p>}
              {detail.withdrawn && <p>사용 중단 상태입니다. 다시 게시하기 전까지 답변에서 제외됩니다.</p>}
            </div>}

            {latestConflict && <div className="documents-conflict" role="alert">
              <div>
                <strong>다른 변경이 먼저 저장됐습니다. 작성 중인 내용은 그대로 보존했습니다.</strong>
                <p>서버 최신 초안: revision {latestConflict.draft.revision_number} · {latestConflict.draft.title} · record version {latestConflict.record_version}</p>
              </div>
              <button type="button" className="documents-button documents-button-secondary" onClick={acceptLatest}>최신 초안 불러오기</button>
            </div>}

            <form ref={editorFormRef} onSubmit={saveDraft} noValidate>
              <DocumentEditor form={form} errors={formErrors} onChange={editField} disabled={writePending} idPrefix="managed-document" />
              {writeFailure && <p className="documents-error" role="alert">{writeFailure}</p>}
              {notice && <p className="documents-success" role="status" aria-live="polite">{notice}</p>}
              {retryableWrite && <button type="button" className="documents-button documents-button-secondary documents-retry"
                disabled={writePending} onClick={() => void executeWrite(retryableWrite)}>
                같은 요청 수동 재시도
              </button>}
              <div className="documents-editor-actions">
                <button type="button" className="documents-button documents-button-secondary" disabled={writePending}
                  onClick={() => navigate("/admin/documents")}>취소</button>
                <button type="submit" className="documents-button documents-button-primary" disabled={writePending}>
                  {writePending && pendingWrite?.kind === "save" ? "초안 저장 중…" : "초안 저장"}
                </button>
                {detail && <button type="button" className="documents-button documents-button-publish"
                  disabled={writePending || editorDirty} onClick={() => openAction("publish")}>
                  {detail.withdrawn ? "다시 게시" : "답변 대상으로 게시"}
                </button>}
                {detail?.published && !detail.withdrawn && <button type="button" className="documents-button documents-button-danger"
                  disabled={writePending || editorDirty} onClick={() => openAction("withdraw")}>사용 중단</button>}
              </div>
              {editorDirty && <p className="documents-help">저장하지 않은 변경이 있습니다. 게시나 사용 중단 전에 초안을 저장해주세요.</p>}
              <p className="documents-local-note">미저장 내용은 자동 저장되지 않으며 새로고침하면 사라집니다. 브라우저에 원문을 저장하지 않습니다.</p>
            </form>
          </> : <div className="documents-state-card" role="alert">
            <p>{writeFailure || "문서를 불러오지 못했습니다."}</p>
            <button type="button" className="documents-button documents-button-secondary" onClick={() => navigate("/admin/documents", true)}>목록으로 돌아가기</button>
          </div>}
        </section>
      ) : <section className="documents-list-panel" aria-labelledby="documents-list-title">
        <div className="documents-list-heading">
          <div>
            <p className="documents-eyebrow">공통 자료</p>
            <h2 id="documents-list-title">등록 문서</h2>
          </div>
          <p>{list ? `${list.total.toLocaleString("ko-KR")}개 문서` : "문서 목록"}</p>
        </div>
        <form className="documents-search" onSubmit={submitSearch} role="search">
          <label htmlFor="documents-search-input">제목 검색</label>
          <input id="documents-search-input" type="search" value={searchInput} maxLength={200}
            onChange={event => setSearchInput(event.target.value)} placeholder="문서 제목을 검색하세요" />
          <label htmlFor="documents-status-filter">상태</label>
          <select id="documents-status-filter" value={filters.status}
            onChange={event => { setListBusy(true); setListError(""); setFilters(current => ({ ...current, status: event.target.value as ListFilters["status"], offset: 0 })); }}>
            <option value="all">전체</option><option value="draft">초안</option>
            <option value="published">게시됨</option><option value="withdrawn">사용 중단</option>
          </select>
          <button type="submit" className="documents-button documents-button-primary">검색</button>
        </form>

        {listBusy ? <p className="documents-loading" role="status">문서 목록을 불러오는 중…</p> : listError ? <div className="documents-state-card" role="alert">
          <p>{listError}</p>
          <button type="button" className="documents-button documents-button-secondary" onClick={() => { setListBusy(true); setListError(""); setListRefresh(value => value + 1); }}>다시 불러오기</button>
          {listErrorKind === "permission" && <p>관리자 인증과 권한 확인은 아직 구성되지 않았습니다.</p>}
        </div> : list?.items.length ? <>
          <ul className="documents-list" aria-label="문서 목록">
            {list.items.map(item => <li key={item.id}>
              <article className="documents-list-card">
                <div className="documents-list-main">
                  <h3><button type="button" className="documents-title-link" onClick={() => navigate(`/admin/documents?id=${encodeURIComponent(item.id)}`)}>{item.draft.title}</button></h3>
                  <p className="documents-list-meta">{item.draft.owner_department || "담당 부서 미지정"} · 수정 {dateLabel(item.updated_at)} · 시행 {dateLabel(item.draft.effective_from)}</p>
                  <p className="documents-list-version">게시본 {item.published ? `v${item.published.revision_number}` : "없음"} · 초안 v{item.draft.revision_number}</p>
                </div>
                <div className="documents-list-side">
                  <span className={`documents-status documents-status-${item.status}`}>{statusLabel(item.status)}</span>
                  <span className="documents-eligibility">{eligibilityLabel(item.eligibility)}</span>
                  <button type="button" className="documents-button documents-button-secondary"
                    onClick={() => navigate(`/admin/documents?id=${encodeURIComponent(item.id)}`)}>편집</button>
                </div>
              </article>
            </li>)}
          </ul>
          <nav className="documents-pagination" aria-label="문서 목록 페이지">
            <button type="button" className="documents-button documents-button-secondary" disabled={filters.offset === 0 || listBusy}
              onClick={() => { setListBusy(true); setFilters(current => ({ ...current, offset: Math.max(0, current.offset - PAGE_SIZE) })); }}>이전</button>
            <span>{pageNumber} / {totalPages} 페이지</span>
            <button type="button" className="documents-button documents-button-secondary" disabled={pageNumber >= totalPages || listBusy}
              onClick={() => { setListBusy(true); setFilters(current => ({ ...current, offset: current.offset + PAGE_SIZE })); }}>다음</button>
          </nav>
        </> : <div className="documents-empty-state">
          <h3>{filters.q || filters.status !== "all" ? "검색 결과가 없습니다." : "등록된 문서가 없습니다."}</h3>
          <p>기존 `/regist-docs`에 등록한 자료는 이 관리 목록에 자동으로 포함되지 않습니다.</p>
          <button type="button" className="documents-button documents-button-primary" onClick={openNewDocument}>첫 문서 초안 만들기</button>
        </div>}
      </section>}

      <footer className="documents-footer">
        <p>로컬 시연 관리 화면입니다. 관리자 인증·권한 검증이 아직 연결되지 않아 사내 네트워크나 외부에 공개하면 안 됩니다.</p>
        <Link href="/chat" onClick={event => {
          if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
          event.preventDefault(); navigate("/chat");
        }}>채팅 화면으로 이동</Link>
      </footer>

      {detail && actionDialog && <DocumentActionDialog action={actionDialog} title={detail.draft.title}
        revision={detail.draft.revision_number} effectiveFrom={effectiveFrom} answerIntegration={answerIntegration}
        busy={actionBusy} onCancel={() => setActionDialog(null)} onConfirm={confirmAction} />}
    </main>
  );
}
