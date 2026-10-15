"use client";

import { useEffect, useRef, useState } from "react";
import { DocumentApiError, maintainDocuments, previewDocumentMaintenance, type MaintenanceAction, type MaintenancePreview, type MaintenanceResult } from "../../lib/api/documents";
import { newIdempotencyKey, retrievalSyncFailureMessage } from "./document-state";

export function DocumentMaintenance({ onBusy, onComplete, onNew, disabled }: {
  onBusy: (busy: boolean) => void; onComplete: (result: MaintenanceResult) => void;
  onNew: () => void; disabled: boolean;
}) {
  const [action, setAction] = useState<MaintenanceAction | null>(null);
  const [notice, setNotice] = useState("");
  return <section className="documents-maintenance" aria-label="문서 작업">
    <div className="documents-maintenance-actions">
      <button type="button" className="documents-button documents-button-primary" disabled={disabled} onClick={onNew}>새 문서 초안</button>
      <div className="documents-maintenance-secondary" role="group" aria-label="전체 문서 관리">
        <button type="button" className="documents-button documents-button-secondary" disabled={disabled} onClick={() => setAction("restore")}>기본 문서 복원</button>
        <button type="button" className="documents-button documents-button-danger" disabled={disabled} onClick={() => setAction("clear")}>모든 문서 삭제</button>
      </div>
    </div>
    {notice && <p role="status" className="documents-success">{notice}</p>}
    {action && <MaintenanceDialog action={action} onBusy={onBusy} onClose={() => setAction(null)} onComplete={result => {
      setNotice(result.action === "clear" ? `문서 ${result.deleted_count}건 삭제 처리를 완료했습니다.` : `기본 문서 ${result.restored_count}건 복원 처리를 완료했습니다.`);
      setAction(null); onComplete(result);
    }} />}
  </section>;
}

function MaintenanceDialog({ action, onBusy, onClose, onComplete }: {
  action: MaintenanceAction; onBusy: (busy: boolean) => void; onClose: () => void; onComplete: (result: MaintenanceResult) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  const [preview, setPreview] = useState<MaintenancePreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [confirmation, setConfirmation] = useState("");
  const [failure, setFailure] = useState("");
  const [failureCode, setFailureCode] = useState("");
  const [mutationApplied, setMutationApplied] = useState(false);
  const [attempted, setAttempted] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const key = useRef("");
  const phrase = action === "clear" ? "전체 삭제" : "기본 문서 복원";

  useEffect(() => {
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const modal = dialog.current;
    modal?.showModal(); cancel.current?.focus();
    return () => { modal?.close(); queueMicrotask(() => { if (trigger?.isConnected) trigger.focus(); }); };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    previewDocumentMaintenance(action, { signal: controller.signal }).then(value => {
      if (!controller.signal.aborted) { setPreview(value); setLoading(false); }
    }).catch(error => {
      if (!controller.signal.aborted) { setFailure(error instanceof Error ? error.message : "상태를 확인하지 못했습니다."); setLoading(false); }
    });
    return () => controller.abort();
  }, [action, refresh]);

  function close() {
    if (busyRef.current) return;
    if (attempted && failure && !window.confirm("작업 결과 또는 검색 반영 상태가 확인되지 않았습니다. 닫으면 같은 요청 재시도 정보가 사라집니다. 닫을까요?")) return;
    onClose();
  }

  async function execute() {
    if (!preview || busyRef.current || confirmation !== phrase) return;
    busyRef.current = true; setBusy(true); onBusy(true); setFailure(""); setFailureCode(""); setMutationApplied(false);
    if (!key.current) key.current = newIdempotencyKey();
    setAttempted(true);
    try {
      const result = await maintainDocuments(preview, key.current);
      busyRef.current = false; setBusy(false); onBusy(false); onComplete(result);
    } catch (error) {
      const retrievalMessage = retrievalSyncFailureMessage(error);
      setFailure(retrievalMessage ?? (error instanceof Error ? error.message : "결과를 확인하지 못했습니다. 같은 요청으로 다시 확인해주세요."));
      if (error instanceof DocumentApiError) {
        setFailureCode(error.code ?? "");
        setMutationApplied(error.details?.document_saved === true);
        if (error.kind === "conflict") { setPreview(null); setAttempted(false); }
      }
      busyRef.current = false; setBusy(false); onBusy(false);
    }
  }
  function reloadPreview() {
    key.current = ""; setAttempted(false); setPreview(null); setFailure(""); setFailureCode(""); setMutationApplied(false); setConfirmation(""); setLoading(true); setRefresh(n => n + 1);
  }
  let followupMessage = "응답을 받지 못했어도 작업이 완료됐을 수 있습니다. 같은 요청으로 결과를 확인하세요.";
  if (failureCode === "retrieval_sync_failed") {
    followupMessage = mutationApplied
      ? "문서 변경은 적용됐습니다. 동일 요청을 다시 보내 검색 반영까지 확인하세요."
      : "문서 변경은 시작되지 않았습니다. 동일 요청으로 다시 시도하세요.";
  } else if (failureCode === "retrieval_sync_busy") {
    followupMessage = "이번 요청은 시작되지 않았습니다. 이전 요청이 있었다면 적용됐을 수 있으므로 동일 요청으로 다시 확인하세요.";
  }
  let submitLabel = phrase;
  if (busy) submitLabel = "문서 작업 및 검색 상태 확인 중…";
  else if (attempted) submitLabel = failureCode === "retrieval_sync_failed" || failureCode === "retrieval_sync_busy"
    ? "같은 요청으로 검색 반영 재시도" : "같은 요청으로 결과 확인";
  return <dialog ref={dialog} className="documents-dialog" aria-labelledby="maintenance-title"
    onCancel={event => { event.preventDefault(); close(); }}>
    <div className="documents-dialog-content">
      <h2 id="maintenance-title">{action === "clear" ? "모든 문서를 삭제할까요?" : "기본 문서로 초기화할까요?"}</h2>
      <p>{action === "clear" ? "초안·게시본·개정 이력이 모두 삭제되며 이번 작업의 백업을 만들지 않습니다." : "현재 문서와 수정 내용을 기본 문서로 교체합니다. 실행 전 문서 백업을 남깁니다."}</p>
      <p>검색 조건과 관계없이 모든 문서가 대상입니다.</p>
      {loading ? <p role="status">전체 문서 상태를 확인하는 중…</p> : preview && <p>현재 전체 문서: {preview.total_count}건 · 작업 후: {preview.restored_count}건</p>}
      {action === "clear" && <p>다음 자정 예약 초기화가 실행되면 기본 문서가 다시 복원될 수 있습니다.</p>}
      {preview && <div className="documents-field"><label htmlFor="maintenance-confirmation">확인을 위해 ‘{phrase}’를 입력하세요</label>
        <input id="maintenance-confirmation" value={confirmation} disabled={busy || attempted} autoComplete="off" onChange={event => setConfirmation(event.target.value)} /></div>}
      {failure && <p role="alert" className="documents-error">{failure}</p>}
      {attempted && failure && <p>{followupMessage}</p>}
      <div className="documents-dialog-actions">
        <button ref={cancel} type="button" className="documents-button documents-button-secondary" disabled={busy} onClick={close}>취소</button>
        {!preview && !loading && <button type="button" className="documents-button documents-button-secondary" onClick={reloadPreview}>현재 상태 다시 확인</button>}
        {preview && <button type="button" className={`documents-button ${action === "clear" ? "documents-button-danger" : "documents-button-primary"}`} disabled={busy || confirmation !== phrase} onClick={() => void execute()}>
          {submitLabel}</button>}
      </div>
    </div>
  </dialog>;
}
