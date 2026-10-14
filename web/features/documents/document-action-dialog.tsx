"use client";

import { useEffect, useRef } from "react";

export type DocumentAction = "publish" | "withdraw";

type DocumentActionDialogProps = {
  action: DocumentAction;
  title: string;
  revision: number;
  effectiveFrom: string | null;
  answerIntegration: "echo" | "connected";
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
};

export function DocumentActionDialog({ action, title, revision, effectiveFrom, answerIntegration, busy, onCancel, onConfirm }: DocumentActionDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const publishing = action === "publish";

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (!dialog.open) dialog.showModal();
    cancelRef.current?.focus();
    return () => { if (dialog.open) dialog.close(); };
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
          <p>초안 revision {revision}</p>
          <p>시행일: {effectiveFrom || "게시 즉시 적용"}</p>
          <p>사용 범위: 공통 자료</p>
          {answerIntegration === "echo" && <p>게시 후에도 현재 채팅은 입력 내용을 그대로 반환합니다. 등록 문서는 아직 답변에 연결되지 않습니다.</p>}
        </div> : <p>기록은 보존되며 새 질문의 답변 대상에서 제외됩니다. 기존 게시본은 다시 게시하기 전까지 사용되지 않습니다.</p>}
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
