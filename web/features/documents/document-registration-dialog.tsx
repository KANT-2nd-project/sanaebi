"use client";

import { useEffect, useRef, useState } from "react";
import { createDocument, DocumentApiError, type DocumentPayload } from "../../lib/api/documents";
import {
  documentPayload, emptyDocumentForm, isDocumentFormDirty, newIdempotencyKey, nextWriteAttempt,
  validateDocumentForm, type DocumentForm, type DocumentWriteAttempt,
} from "./document-state";
import { DocumentEditor } from "./document-editor";

type DocumentRegistrationDialogProps = {
  initialBody: string;
  onClose: () => void;
  onSaved: (title: string) => void;
};

export function DocumentRegistrationDialog({ initialBody, onClose, onSaved }: DocumentRegistrationDialogProps) {
  const [form, setForm] = useState<DocumentForm>(() => ({ ...emptyDocumentForm(), body: initialBody }));
  const [baselineForm] = useState(form);
  const [errors, setErrors] = useState<ReturnType<typeof validateDocumentForm>>({});
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState("");
  const [failureKind, setFailureKind] = useState<DocumentApiError["kind"] | "">("");
  const [attempt, setAttempt] = useState<DocumentWriteAttempt | null>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const formRef = useRef<HTMLFormElement>(null);
  const errorSummaryRef = useRef<HTMLDivElement>(null);
  const pendingRef = useRef(false);
  const dirty = isDocumentFormDirty(form, baselineForm);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialog.showModal();
    dialog.querySelector<HTMLElement>("input, textarea")?.focus();
    return () => {
      if (dialog.open) dialog.close();
      queueMicrotask(() => { if (trigger?.isConnected) trigger.focus(); });
    };
  }, []);

  useEffect(() => {
    if (!dirty && !attempt) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty, attempt]);

  function requestClose() {
    if ((dirty || attempt) && !window.confirm("저장하지 않은 등록 내용이 사라질 수 있습니다. 닫을까요?")) return;
    onClose();
  }

  function updateField(field: keyof DocumentForm, value: string) {
    setForm(current => ({ ...current, [field]: value }));
    setErrors(current => ({ ...current, [field]: undefined }));
    setFailure("");
    setFailureKind("");
    setAttempt(null);
  }

  async function save(retryAttempt?: DocumentWriteAttempt) {
    if (pendingRef.current) return;
    const fieldErrors = validateDocumentForm(form);
    setErrors(fieldErrors);
    if (Object.keys(fieldErrors).length) {
      requestAnimationFrame(() => errorSummaryRef.current?.focus());
      return;
    }

    const payload = documentPayload(form);
    const current = retryAttempt ?? nextWriteAttempt(attempt, "POST", "/api/documents", payload, newIdempotencyKey);
    setAttempt(current);
    pendingRef.current = true;
    setBusy(true);
    setFailure("");
    try {
      await createDocument(current.body as DocumentPayload, current.key);
      onSaved(form.title);
      onClose();
    } catch (error) {
      const apiError = error instanceof DocumentApiError ? error : null;
      setFailure(apiError?.message ?? "문서를 저장하지 못했습니다. 입력 내용은 보존했습니다.");
      setFailureKind(apiError?.kind ?? "request");
    } finally {
      pendingRef.current = false;
      setBusy(false);
    }
  }

  function handleCancel(event: React.SyntheticEvent<HTMLDialogElement>) {
    event.preventDefault();
    if (!busy) requestClose();
  }

  return (
    <dialog ref={dialogRef} className="documents-dialog documents-registration-dialog" aria-labelledby="registration-title"
      onCancel={handleCancel} onClick={event => { if (event.target === event.currentTarget && !busy) requestClose(); }}>
      <div className="documents-dialog-content">
        <div className="documents-dialog-heading">
          <div>
            <p className="documents-eyebrow">문서 등록</p>
            <h2 id="registration-title">질문 내용을 문서 초안으로 등록</h2>
          </div>
          <button type="button" className="documents-icon-button" aria-label="닫기" disabled={busy} onClick={requestClose}>×</button>
        </div>
        <p className="documents-callout">입력한 내용을 질문으로 보내지 않습니다. 저장한 초안은 검토 후 별도로 게시해야 합니다.</p>
        <form ref={formRef} onSubmit={event => { event.preventDefault(); void save(); }} noValidate>
          <DocumentEditor form={form} errors={errors} onChange={updateField} disabled={busy} idPrefix="chat-registration"
            errorSummaryRef={errorSummaryRef} />
          {failure && <p className="documents-error" role="alert">{failure}</p>}
          <div className="documents-dialog-actions">
            {attempt && ["timeout", "network", "gateway"].includes(failureKind)
              && <button type="button" className="documents-button documents-button-secondary" disabled={busy} onClick={() => void save(attempt)}>같은 요청 다시 시도</button>}
            <button type="button" className="documents-button documents-button-secondary" disabled={busy} onClick={requestClose}>취소</button>
            <button type="submit" className="documents-button documents-button-primary" disabled={busy}>
              {busy ? "저장 중…" : "초안으로 저장"}
            </button>
          </div>
        </form>
      </div>
    </dialog>
  );
}
