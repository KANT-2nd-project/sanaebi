"use client";

import { forwardRef } from "react";
import type { DocumentForm, DocumentFormErrors } from "./document-state";

const fieldLabels: Record<keyof DocumentForm, string> = {
  title: "문서 제목",
  body: "문서 원문",
  source_label: "출처 이름",
  source_url: "출처 주소",
  owner_department: "담당 부서",
  effective_from: "시행일",
};

export function documentFieldId(idPrefix: string, field: keyof DocumentForm): string {
  return `${idPrefix}-${field}`;
}

type DocumentErrorSummaryProps = {
  errors: DocumentFormErrors;
  idPrefix: string;
};

export const DocumentErrorSummary = forwardRef<HTMLDivElement, DocumentErrorSummaryProps>(
  function DocumentErrorSummary({ errors, idPrefix }, ref) {
    const entries = (Object.keys(fieldLabels) as (keyof DocumentForm)[])
      .filter(field => Boolean(errors[field]));

    if (!entries.length) return null;

    return (
      <div ref={ref} className="documents-error-summary" role="alert" aria-labelledby={`${idPrefix}-error-summary-title`} tabIndex={-1}>
        <p id={`${idPrefix}-error-summary-title`}><strong>입력 내용을 확인해주세요</strong></p>
        <ul>
          {entries.map(field => (
            <li key={field}>
              <a href={`#${documentFieldId(idPrefix, field)}`} onClick={event => {
                event.preventDefault();
                const input = document.getElementById(documentFieldId(idPrefix, field));
                const section = input?.closest("details");
                if (section) section.open = true;
                input?.focus();
              }}>
                {fieldLabels[field]}: {errors[field]}
              </a>
            </li>
          ))}
        </ul>
      </div>
    );
  },
);

DocumentErrorSummary.displayName = "DocumentErrorSummary";
