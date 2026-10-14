"use client";

import type { DocumentForm, DocumentFormErrors } from "./document-state";

type DocumentEditorProps = {
  form: DocumentForm;
  errors: DocumentFormErrors;
  onChange: (field: keyof DocumentForm, value: string) => void;
  disabled?: boolean;
  idPrefix?: string;
};

export function DocumentEditor({ form, errors, onChange, disabled = false, idPrefix = "document" }: DocumentEditorProps) {
  const field = (name: keyof DocumentForm) => `${idPrefix}-${name}`;
  const issue = (name: keyof DocumentForm) => errors[name] ? `${idPrefix}-${name}-error` : undefined;

  return (
    <div className="documents-editor-fields">
      <div className="documents-field">
        <label htmlFor={field("title")}>문서 제목 <span aria-hidden="true">*</span></label>
        <input id={field("title")} name="title" value={form.title} maxLength={200} disabled={disabled}
          aria-invalid={Boolean(errors.title)} aria-describedby={issue("title")}
          onChange={event => onChange("title", event.target.value)} />
        {errors.title && <p id={issue("title")} className="documents-field-error" role="alert">{errors.title}</p>}
      </div>
      <div className="documents-field">
        <label htmlFor={field("body")}>문서 원문 <span aria-hidden="true">*</span></label>
        <p id={`${field("body")}-help`} className="documents-help">원문을 그대로 입력하세요. 등록 내용은 채팅 답변에 아직 사용되지 않습니다.</p>
        <textarea id={field("body")} name="body" value={form.body} maxLength={50_000} rows={12} disabled={disabled}
          aria-invalid={Boolean(errors.body)} aria-describedby={`${field("body")}-help${errors.body ? ` ${issue("body")}` : ""}`}
          onChange={event => onChange("body", event.target.value)} />
        {errors.body && <p id={issue("body")} className="documents-field-error" role="alert">{errors.body}</p>}
        <p className="documents-character-count">{form.body.length.toLocaleString("ko-KR")} / 50,000자</p>
      </div>
      <details className="documents-metadata">
        <summary>추가 정보</summary>
        <div className="documents-metadata-fields">
          <div className="documents-field">
            <label htmlFor={field("source_label")}>출처 이름</label>
            <input id={field("source_label")} name="source_label" value={form.source_label} maxLength={200} disabled={disabled}
              aria-invalid={Boolean(errors.source_label)} aria-describedby={issue("source_label")}
              onChange={event => onChange("source_label", event.target.value)} />
            {errors.source_label && <p id={issue("source_label")} className="documents-field-error" role="alert">{errors.source_label}</p>}
          </div>
          <div className="documents-field">
            <label htmlFor={field("source_url")}>출처 주소</label>
            <input id={field("source_url")} name="source_url" type="url" inputMode="url" value={form.source_url} maxLength={2_048} disabled={disabled}
              aria-invalid={Boolean(errors.source_url)} aria-describedby={issue("source_url")}
              onChange={event => onChange("source_url", event.target.value)} />
            {errors.source_url && <p id={issue("source_url")} className="documents-field-error" role="alert">{errors.source_url}</p>}
          </div>
          <div className="documents-field">
            <label htmlFor={field("owner_department")}>담당 부서</label>
            <input id={field("owner_department")} name="owner_department" value={form.owner_department} maxLength={200} disabled={disabled}
              aria-invalid={Boolean(errors.owner_department)} aria-describedby={issue("owner_department")}
              onChange={event => onChange("owner_department", event.target.value)} />
            {errors.owner_department && <p id={issue("owner_department")} className="documents-field-error" role="alert">{errors.owner_department}</p>}
          </div>
          <div className="documents-field">
            <label htmlFor={field("effective_from")}>시행일</label>
            <input id={field("effective_from")} name="effective_from" type="date" value={form.effective_from} disabled={disabled}
              aria-invalid={Boolean(errors.effective_from)} aria-describedby={issue("effective_from")}
              onChange={event => onChange("effective_from", event.target.value)} />
            {errors.effective_from && <p id={issue("effective_from")} className="documents-field-error" role="alert">{errors.effective_from}</p>}
          </div>
        </div>
      </details>
    </div>
  );
}
