"use client";

import { useEffect, useRef } from "react";

export type DocumentAction = "publish" | "withdraw";

type DocumentActionDialogProps = {
  action: DocumentAction;
  title: string;
  revision: number;
  effectiveFrom: string | null;
  answerIntegration?: "echo" | "connected" | null;
  previousRevision?: number | null;
  reviewStatus?: string;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
};

export function DocumentActionDialog({ action, title, revision, effectiveFrom, answerIntegration, previousRevision, reviewStatus, busy, onCancel, onConfirm }: DocumentActionDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const publishing = action === "publish";

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    if (!dialog.open) dialog.showModal();
    cancelRef.current?.focus();
    return () => {
      if (dialog.open) dialog.close();
      queueMicrotask(() => { if (trigger?.isConnected) trigger.focus(); });
    };
  }, []);

  function handleCancel(event: React.SyntheticEvent<HTMLDialogElement>) {
    event.preventDefault();
    if (!busy) onCancel();
  }

  return (
    <dialog ref={dialogRef} className="documents-dialog" aria-labelledby="documents-dialog-title" onCancel={handleCancel}
      onClick={event => { if (event.target === event.currentTarget && !busy) onCancel(); }}>
      <div className="documents-dialog-content">
        <p className="documents-eyebrow">문서 상태 변경</p>
        <h2 id="documents-dialog-title">{publishing ? "답변 대상으로 게시할까요?" : "이 문서를 사용 중단할까요?"}</h2>
        <p className="documents-dialog-document">{title}</p>
        {publishing ? <div className="documents-dialog-details">
          <p>게시할 초안: revision {revision}</p>
          {previousRevision !== undefined && <p>{previousRevision === null
            ? "교체할 현재 게시본: 없음"
            : `교체할 현재 게시본: revision ${previousRevision}`}</p>}
          <p>시행일: {effectiveFrom || "게시 즉시 적용"}</p>
          <p>검수 상태: {reviewStatus === "ai_reviewed" ? "AI 검수 기록" : reviewStatus === "unreviewed" ? "미검수" : reviewStatus || "확인되지 않음"}. 게시 처리는 사람 검수 승인을 뜻하지 않습니다.</p>
          <p>사용 범위: 공통 자료</p>
          {answerIntegration === "connected"
            ? <p>문서 답변 경로는 연결되어 있습니다. 이는 모델 가용성이나 실제 답변 성공을 보장하지 않습니다.</p>
            : answerIntegration === "echo"
              ? <p>문서 답변 경로가 연결되지 않은 상태입니다. 게시만으로 채팅 답변이 생성되지는 않습니다.</p>
              : <p>문서 답변 경로 상태를 확인할 수 없습니다.</p>}
        </div> : <div><p>현재 게시본: v{revision}</p><p>이 문서의 게시본을 다음 질문의 답변 근거에서 제외하며 초안과 기록은 보존합니다.</p></div>}
        <div className="documents-dialog-actions">
          <button ref={cancelRef} type="button" className="documents-button documents-button-secondary" disabled={busy} onClick={onCancel}>취소</button>
          <button type="button" className={`documents-button ${publishing ? "documents-button-primary" : "documents-button-danger"}`}
            disabled={busy} onClick={onConfirm}>
            {busy ? "처리 중…" : publishing ? "게시 확인" : "사용 중단"}
          </button>
        </div>
      </div>
    </dialog>
  );
}
