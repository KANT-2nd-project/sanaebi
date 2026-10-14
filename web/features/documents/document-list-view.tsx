"use client";
import Link from "next/link";
import type { DocumentSummary } from "../../lib/api/documents";
import { eligibilityLabel, hasDraftChanges } from "./document-view-state";

export function DocumentListView({ items, hrefFor, onOpen }: {
  items: DocumentSummary[]; hrefFor: (id: string) => string; onOpen: (id: string) => void;
}) {
  return <table className="documents-table"><caption className="sr-only">등록 문서 · 최근 수정순</caption>
    <thead><tr><th scope="col">문서 제목</th><th scope="col">답변 사용</th><th scope="col">수정 상태</th><th scope="col">최근 수정</th></tr></thead>
    <tbody>{items.map(item => <tr key={item.id}>
      <th scope="row"><Link data-document-id={item.id} href={hrefFor(item.id)} onClick={event => {
        if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault(); onOpen(item.id);
      }}>{item.draft.title}</Link>{item.draft.owner_department && <p className="documents-help">{item.draft.owner_department}</p>}</th>
      <td data-label="답변 사용"><span className={`documents-status documents-status-${item.status}`}>{eligibilityLabel(item.eligibility)}</span></td>
      <td data-label="수정 상태">{hasDraftChanges(item) ? <span className="documents-change-badge">수정 초안 있음</span> : item.published ? "게시본과 동일" : "게시 전"}</td>
      <td data-label="최근 수정"><time dateTime={item.updated_at}>{item.updated_at.slice(0, 10)}</time></td>
    </tr>)}</tbody></table>;
}
