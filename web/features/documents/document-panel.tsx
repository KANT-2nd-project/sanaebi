"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import {
  createDocument, DocumentApiError, getDocument, listDocuments,
  publishDocument, updateDocument, withdrawDocument,
  type DocumentDetail, type DocumentListResponse, type DocumentPayload,
  type DocumentStatus,
} from "../../lib/api/documents";
import {
  documentPayload, emptyDocumentForm, formFromRevision, isDocumentFormDirty,
  newIdempotencyKey, nextWriteAttempt, validateDocumentForm,
  type DocumentForm, type DocumentFormErrors, type DocumentWriteAttempt,
} from "./document-state";
import { DocumentRouteState } from "./document-route-state";
import { DocumentActionDialog, type DocumentAction } from "./document-action-dialog";
import { DocumentEditor } from "./document-editor";
import { DocumentReadView } from "./document-read-view";
import { DocumentListView } from "./document-list-view";
import { parseDocumentView, documentViewUrl, type DocumentView } from "./document-view-state";

const PAGE_SIZE = 20;
type WriteKind = "save" | "publish" | "withdraw";
type PendingWrite = { kind: WriteKind; attempt: DocumentWriteAttempt; documentId: string | null; originRoute: string };
function errorMessage(error: unknown, fallback: string): { message: string; kind: DocumentApiError["kind"] | "" } {
  if (!(error instanceof DocumentApiError)) return { message: fallback, kind: "" };
  if (error.kind === "permission") return { message: "이 문서 관리 화면을 볼 권한이 없습니다.", kind: error.kind };
  if (error.kind === "not-found") return { message: "문서를 찾을 수 없습니다. 목록을 새로고침해주세요.", kind: error.kind };
  return { message: error.message, kind: error.kind };
}

function isTransient(kind: string) {
  return ["timeout", "network", "gateway"].includes(kind);
}

export function DocumentPanel() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const search = searchParams?.toString() ?? "";
  const view = useMemo(() => parseDocumentView(search), [search]);
  const selectedId = view.id;
  const isNew = view.isNew;
  const editorOpen = view.editing;
  const detailOpen = Boolean(selectedId || isNew);
  const listUrl = documentViewUrl({ ...view, id: null, isNew: false, editing: false, revision: null });
  const filters = { q: view.q, status: view.status, offset: (view.page - 1) * PAGE_SIZE };
  const routeUrl = `${pathname ?? "/admin/documents"}${search ? `?${search}` : ""}`;
  const [routeState] = useState(() => new DocumentRouteState(routeUrl));

  const [searchInput, setSearchInput] = useState(view.q);
  const [statusInput, setStatusInput] = useState(view.status);
  const [list, setList] = useState<DocumentListResponse | null>(null);
  const [listQueryKey, setListQueryKey] = useState("");
  const queryKey = JSON.stringify([view.q, view.status, view.page]);
  const [listBusy, setListBusy] = useState(true);
  const [listError, setListError] = useState("");
  const [listRefresh, setListRefresh] = useState(0);

  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  const [detailBusy, setDetailBusy] = useState(false);
  const [form, setForm] = useState<DocumentForm>(() => emptyDocumentForm());
  const [baselineForm, setBaselineForm] = useState<DocumentForm>(() => emptyDocumentForm());
  const [formErrors, setFormErrors] = useState<DocumentFormErrors>({});
  const [conflictDocumentId, setConflictDocumentId] = useState<string | null>(null);
  const [conflictBusy, setConflictBusy] = useState(false);
  const [conflictError, setConflictError] = useState("");
  const conflictRequest = useRef<AbortController | null>(null);
  const [latestConflict, setLatestConflict] = useState<DocumentDetail | null>(null);
  const [writeFailure, setWriteFailure] = useState("");
  const [writeFailureKind, setWriteFailureKind] = useState("");
  const [writePending, setWritePending] = useState(false);
  const [notice, setNotice] = useState("");
  const [pendingWrite, setPendingWrite] = useState<PendingWrite | null>(null);
  const [actionDialog, setActionDialog] = useState<DocumentAction | null>(null);
  const [actionBusy, setActionBusy] = useState(false);

  const editorFormRef = useRef<HTMLFormElement>(null);
  const errorSummaryRef = useRef<HTMLDivElement>(null);
  const returnPosition = useRef<{ id: string; y: number } | null>(null);
  const focusedResource = useRef<string | null>(null);
  const [focusReady, setFocusReady] = useState(0);
  const requestInFlight = useRef(false);
  const pendingWriteRef = useRef<PendingWrite | null>(null);
  const loadedResourceKey = useRef<string | null>(null);
  const dirtyRef = useRef(false);
  const resourceKey = selectedId ? `document:${selectedId}:${editorOpen ? "edit" : "read"}` : isNew ? "new-document" : "document-list";
  const editorDirty = editorOpen && isDocumentFormDirty(form, baselineForm);
  useEffect(() => {
    if (routeState.canLoad(routeUrl)) dirtyRef.current = editorDirty;
  }, [editorDirty, routeState, routeUrl]);

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
    const previousUrl = routeState.acceptedUrl;
    const transition = routeState.observe(url, {
      dirty: dirtyRef.current || Boolean(pendingWriteRef.current),
      pendingWrite: requestInFlight.current,
      confirmDiscard: () => window.confirm("저장하지 않은 문서 내용이 사라질 수 있습니다. 이동할까요?"),
    });
    if (transition.kind === "accepted" && previousUrl !== url) {
      dirtyRef.current = false;
      conflictRequest.current?.abort();
      conflictRequest.current = null;
      setConflictDocumentId(null);
      setConflictBusy(false);
      setConflictError("");
      setCurrentWrite(null);
      setLatestConflict(null);
    }
    if (transition.kind === "blocked") router.replace(transition.restoreUrl);
  }, [routeState, router, setCurrentWrite]);

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

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    setSearchInput(view.q);
    setStatusInput(view.status);
  }, [routeUrl, view.q, view.status]);

  useEffect(() => {
    const canonical = documentViewUrl(view);
    if (canonical !== routeUrl && routeState.canLoad(routeUrl) && !dirtyRef.current && !requestInFlight.current) {
      routeState.approve(canonical);
      router.replace(canonical, { scroll: false });
    }
  }, [view, routeUrl, routeState, router]);

  useEffect(() => {
    const controller = new AbortController();
    setListBusy(true);
    setListError("");
    listDocuments({ q: view.q, status: view.status, limit: PAGE_SIZE, offset: (view.page - 1) * PAGE_SIZE }, { signal: controller.signal })
      .then(result => {
        if (controller.signal.aborted) return;
        setList(result); setListQueryKey(JSON.stringify([view.q, view.status, view.page])); setListBusy(false);
      })
      .catch(error => {
        if (error instanceof DocumentApiError && error.kind === "aborted") return;
        const issue = errorMessage(error, "문서 목록을 불러오지 못했습니다.");
        setListError(issue.message);
        setList(null);
        setListBusy(false);
      });
    return () => controller.abort();
  }, [view.q, view.status, view.page, listRefresh]);

  useEffect(() => {
    if (detailOpen || listBusy || !list || listError || listQueryKey !== queryKey) return;
    const maxPage = Math.max(1, Math.ceil(list.total / PAGE_SIZE));
    if (view.page > maxPage) {
      const url = documentViewUrl({ ...view, page: maxPage });
      routeState.approve(url);
      router.replace(url, { scroll: false });
    }
  }, [detailOpen, listBusy, list, listError, listQueryKey, queryKey, view, router, routeState]);

  useEffect(() => {
    if (detailOpen) {
      if (detailBusy || loadedResourceKey.current !== resourceKey || (!detail && !isNew) || focusedResource.current === resourceKey) return;
      focusedResource.current = resourceKey;
      document.getElementById("document-editor-title")?.focus({ preventScroll: true });
    } else if (!listBusy && list && listQueryKey === queryKey) {
      focusedResource.current = null;
      const position = returnPosition.current;
      if (position) {
        const link = Array.from(document.querySelectorAll<HTMLAnchorElement>("[data-document-id]")).find(node => node.dataset.documentId === position.id);
        link?.focus({ preventScroll: true });
        window.scrollTo(0, position.y);
        returnPosition.current = null;
      }
    }
  }, [detailOpen, detailBusy, detail, isNew, resourceKey, listBusy, list, listQueryKey, queryKey, focusReady]);
  /* eslint-enable react-hooks/set-state-in-effect */

  useEffect(() => () => {
    conflictRequest.current?.abort();
    conflictRequest.current = null;
  }, []);

  // Keep the editor draft aligned with the static route's client-side query state.
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (!routeState.canLoad(routeUrl)) return;
    if (loadedResourceKey.current === resourceKey) {
      setDetailBusy(false);
      return;
    }
    if (isNew) {
      loadedResourceKey.current = resourceKey;
      setFocusReady(value => value + 1);
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
    if (conflictRequest.current) return;
    const controller = new AbortController();
    conflictRequest.current = controller;
    const generation = routeState.generation;
    const originRoute = routeUrl;
    setConflictDocumentId(documentId);
    setConflictBusy(true);
    setConflictError("");
    setLatestConflict(null);
    const isCurrent = () => !controller.signal.aborted && generation === routeState.generation
      && routeState.canLoad(originRoute) && conflictRequest.current === controller;
    try {
      const current = await getDocument(documentId, { signal: controller.signal });
      if (!isCurrent() || current.id !== documentId) return;
      setLatestConflict(current);
    } catch {
      if (isCurrent()) setConflictError("서버 최신본을 확인하지 못했습니다. 내 입력은 유지했습니다. 다시 확인해주세요.");
    } finally {
      if (conflictRequest.current === controller) {
        conflictRequest.current = null;
        setConflictBusy(false);
      }
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
      setConflictDocumentId(null);
      conflictRequest.current?.abort();
      conflictRequest.current = null;
      setConflictBusy(false);
      setConflictError("");
      setFormErrors({});
      setNotice(pending.kind === "publish" ? `개정 v${result.published?.revision_number}을 게시했습니다. 시행일 조건에 따라 다음 질문에 적용됩니다.`
        : pending.kind === "withdraw" ? "문서를 사용 중단했습니다. 기록은 보존되며 다음 질문의 답변 근거에서 제외됩니다." : `초안 v${result.draft.revision_number}을 저장했습니다. 게시 전에는 답변에 반영되지 않습니다.`);
      setActionDialog(null);
      if (pending.kind === "save") {
        const path = documentViewUrl({ ...view, id: result.id, isNew: false, editing: false, revision: "draft" });
        dirtyRef.current = false;
        loadedResourceKey.current = `document:${result.id}:read`;
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
      queueMicrotask(() => errorSummaryRef.current?.focus());
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
    if (!latestConflict || !detail || latestConflict.id !== detail.id || !routeState.canLoad(routeUrl)) return;
    if (editorDirty && !window.confirm("최신 문서로 바꾸면 지금 작성 중인 내용이 사라집니다. 계속할까요?")) return;
    const nextForm = formFromRevision(latestConflict.draft);
    setDetail(latestConflict);
    setForm(nextForm);
    setBaselineForm(nextForm);
    setLatestConflict(null);
    setConflictDocumentId(null);
    setConflictError("");
    setCurrentWrite(null);
    setWriteFailure("");
    setWriteFailureKind("");
    setNotice("최신 초안을 불러왔습니다. 필요한 내용을 다시 확인해주세요.");
  }

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    navigate(documentViewUrl({ ...view, q: searchInput, status: statusInput, page: 1 }));
  }

  function resetSearch() {
    setSearchInput("");
    setStatusInput("all");
    navigate(documentViewUrl({ ...view, q: "", status: "all", page: 1 }));
  }

  function openNewDocument() {
    navigate(documentViewUrl({ ...view, id: null, isNew: true, editing: true, revision: null }));
  }

  const pageNumber = Math.floor(filters.offset / PAGE_SIZE) + 1;
  const totalPages = Math.max(1, Math.ceil((list?.total ?? 0) / PAGE_SIZE));
  const effectiveFrom = detail?.draft.effective_from ?? null;
  const retryableWrite = pendingWrite && isTransient(writeFailureKind) ? pendingWrite : null;

  function detailUrl(id: string, patch: Partial<DocumentView> = {}) {
    return documentViewUrl({ ...view, id, isNew: false, editing: false, revision: null, ...patch });
  }

  async function copyInput() {
    try {
      await navigator.clipboard.writeText(JSON.stringify(documentPayload(form), null, 2));
      setNotice("작성 중인 제목·본문·추가 정보를 클립보드에 복사했습니다.");
    } catch {
      setNotice("복사하지 못했습니다. 아래 편집 입력은 그대로 유지됩니다. 직접 선택해 복사해주세요.");
    }
  }

  const pagination = list && totalPages > 1 && <nav className="documents-pagination" aria-label="문서 목록 페이지">

    <div><button type="button" className="documents-button documents-button-secondary" disabled={pageNumber <= 1 || listBusy}
      onClick={() => navigate(documentViewUrl({ ...view, page: pageNumber - 1 }))}>이전</button>
      <span> {pageNumber} / {totalPages} 페이지 </span>
      <button type="button" className="documents-button documents-button-secondary" disabled={pageNumber >= totalPages || listBusy}
      onClick={() => navigate(documentViewUrl({ ...view, page: pageNumber + 1 }))}>다음</button></div>
  </nav>;

  return (
    <main className="documents-page">
      <header className="documents-header">
        <Link href="/" className="documents-brand" onClick={event => {
          if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
          event.preventDefault(); navigate("/");
        }}>사내<span>비</span></Link>
        <nav aria-label="문서 관리 메뉴"><Link href="/chat" className="documents-nav-link" onClick={event => {
          if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
          event.preventDefault(); navigate("/chat");
        }}>채팅으로 돌아가기</Link><button type="button" className="documents-button documents-button-primary" disabled={writePending} onClick={openNewDocument}>새 문서 초안</button></nav>
      </header>
      <section className="documents-intro documents-intro-compact" aria-labelledby="documents-title">
        <p className="documents-callout">등록한 문서는 매일 자정(한국 시간)에 초기화됩니다.</p>
        <h1 id="documents-title">문서 관리</h1><p>답변에 사용할 자료를 확인하고 게시합니다.</p>
      </section>
      {detailOpen ? <section className="documents-editor-panel" aria-labelledby="document-editor-title">
        <div className="documents-editor-toolbar"><button type="button" className="documents-text-button" disabled={writePending} onClick={() => navigate(listUrl)}>← 검색 결과로</button>
          <span>{isNew ? "새 초안" : editorOpen ? "초안 편집" : "문서 읽기"}</span></div>
        {detailBusy ? <p role="status">문서를 불러오는 중…</p> : detail || isNew ? <>
          {conflictDocumentId === detail?.id && <div className="documents-conflict" role="alert"><strong>다른 변경이 먼저 저장됐습니다. 내 입력은 유지했습니다.</strong>
            {conflictBusy && <p role="status">서버 최신본 확인 중…</p>}
            {conflictError && <p role="alert">{conflictError}</p>}
            {latestConflict && <details><summary>서버 최신 초안 v{latestConflict.draft.revision_number} 확인</summary><h3>{latestConflict.draft.title}</h3><div className="documents-plain-text">{latestConflict.draft.body}</div></details>}
            {editorOpen && <button type="button" className="documents-button documents-button-secondary" onClick={() => void copyInput()}>내 입력 복사</button>}
            {!latestConflict && <button type="button" className="documents-button documents-button-secondary" disabled={conflictBusy || writePending} onClick={() => void fetchLatestConflict(conflictDocumentId!)}>서버 최신본 다시 확인</button>}
            {latestConflict && <button type="button" className="documents-button documents-button-secondary" disabled={writePending || conflictBusy} onClick={acceptLatest}>최신 초안 불러오기</button>}</div>}
          {editorOpen ? <>
            <h2 id="document-editor-title" tabIndex={-1}>{isNew ? "새 문서 초안" : "초안 편집"}</h2>
            <p className="documents-help">{detail?.published && !detail.withdrawn ? `현재 답변 대상은 게시본 v${detail.published.revision_number}입니다. 초안 저장만으로 바뀌지 않습니다.` : "초안은 게시하기 전까지 답변에 사용되지 않습니다."} 수정한 개정은 미검수로 저장됩니다.</p>
            <form className="documents-editor-form" ref={editorFormRef} onSubmit={saveDraft} noValidate>
              <DocumentEditor form={form} errors={formErrors} onChange={editField} disabled={writePending} idPrefix="managed-document" errorSummaryRef={errorSummaryRef} />
              <div className="documents-editor-actions"><button type="button" className="documents-button documents-button-secondary" disabled={writePending} onClick={() => navigate(detail ? detailUrl(detail.id) : listUrl)}>취소</button>
                <button type="submit" className="documents-button documents-button-primary" disabled={writePending}>{writePending ? "초안 저장 중…" : "초안 저장"}</button></div>
              {editorDirty && <p className="documents-help">저장하지 않은 변경이 있습니다.</p>}
              <p className="documents-local-note">자동 저장하지 않습니다. 새로고침하면 미저장 내용이 사라질 수 있습니다.</p>
            </form>
          </> : detail && <DocumentReadView detail={detail} revision={view.revision} busy={writePending}
            onRevision={revision => navigate(detailUrl(detail.id, { revision }))} onEdit={() => navigate(detailUrl(detail.id, { editing: true }))}
            onPublish={() => openAction("publish")} onWithdraw={() => openAction("withdraw")} />}
        </> : <div role="alert"><h2 id="document-editor-title">문서를 불러올 수 없습니다.</h2><p>{writeFailure}</p>
          <button type="button" className="documents-button documents-button-secondary" onClick={() => navigate(listUrl)}>목록으로 돌아가기</button></div>}
        {writeFailure && (detail || isNew) && <p className="documents-error" role="alert">{writeFailure}</p>}
        {notice && <p className="documents-success" role="status">{notice}</p>}
        {retryableWrite && <button type="button" className="documents-button documents-button-secondary" disabled={writePending} onClick={() => void executeWrite(retryableWrite)}>같은 요청 수동 재시도</button>}
      </section> : <section className="documents-list-panel" aria-labelledby="documents-list-title">
        <div className="documents-list-heading"><h2 id="documents-list-title">등록 문서</h2><p className="documents-help">최근 수정순 · 20건씩 표시</p></div>
        <form className="documents-search" onSubmit={submitSearch} role="search" aria-describedby="documents-search-help">
          <div className="documents-search-field"><label htmlFor="documents-search-input">제목 검색</label>
            <input id="documents-search-input" type="search" value={searchInput} maxLength={200} onChange={event => setSearchInput(event.target.value)} placeholder="초안 제목을 검색하세요" /></div>
          <div className="documents-search-field"><label htmlFor="documents-status-filter">상태</label>
            <select id="documents-status-filter" value={statusInput} onChange={event => setStatusInput(event.target.value as DocumentStatus | "all")}>
              <option value="all">전체</option><option value="draft">초안</option><option value="published">게시됨</option><option value="withdrawn">사용 중단</option>
            </select></div>
          <div className="documents-search-actions"><button type="submit" className="documents-button documents-button-primary">검색</button>
            <button type="button" className="documents-button documents-button-secondary" disabled={!searchInput && statusInput === "all" && !view.q && view.status === "all"} onClick={resetSearch}>조건 초기화</button></div>
        </form>
        <p id="documents-search-help" className="documents-help">초안 제목을 검색합니다. 제목과 상태를 선택한 뒤 검색을 눌러 함께 적용하세요.</p>
        <div className="documents-results-summary" role="status">
          <p>{listBusy ? "결과 확인 중" : listError ? "결과를 확인할 수 없습니다." : list ? `전체 ${list.total}건${list.total ? ` 중 ${filters.offset + 1}–${Math.min(filters.offset + list.items.length, list.total)}` : ""}` : ""}</p>
          <p className="documents-help">적용 조건: {view.q ? `초안 제목 ‘${view.q}’ · ` : ""}{{ all: "전체", draft: "초안", published: "게시됨", withdrawn: "사용 중단" }[view.status]}</p>
        </div>
        {listBusy ? <p role="status">문서 목록을 불러오는 중…</p> : listError ? <div role="alert"><p>{listError}</p><button type="button" className="documents-button documents-button-secondary" onClick={() => void refreshList()}>다시 불러오기</button>
          </div> : list?.items.length ? <>
          <DocumentListView items={list.items} hrefFor={id => detailUrl(id)} onOpen={id => { returnPosition.current = { id, y: window.scrollY }; navigate(detailUrl(id)); }} />{pagination}
        </> : <div className="documents-empty-state"><h3>{view.q || view.status !== "all" ? "조건에 맞는 문서가 없습니다." : "등록된 문서가 없습니다."}</h3>
          <p>{view.q || view.status !== "all" ? "검색어나 상태 조건을 바꿔보세요." : "첫 문서를 초안으로 등록하고 검토한 뒤 게시하세요."}</p>
          {view.q || view.status !== "all" ? <button type="button" className="documents-button documents-button-secondary" onClick={resetSearch}>조건 초기화</button>
            : <button type="button" className="documents-button documents-button-primary" onClick={openNewDocument}>첫 문서 초안 만들기</button>}</div>}
      </section>}
      {detail && actionDialog && <DocumentActionDialog action={actionDialog} title={(actionDialog === "withdraw" ? detail.published ?? detail.draft : detail.draft).title} revision={(actionDialog === "withdraw" ? detail.published ?? detail.draft : detail.draft).revision_number}
        previousRevision={detail.published?.revision_number ?? null} reviewStatus={detail.draft.metadata?.review_status}
        effectiveFrom={effectiveFrom} busy={actionBusy} onCancel={() => setActionDialog(null)} onConfirm={confirmAction} />}
    </main>
  );
}
