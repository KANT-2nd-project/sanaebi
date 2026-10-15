"use client";
import Link from "next/link";
import type { DocumentSummary } from "../../lib/api/documents";
import { eligibilityLabel, hasDraftChanges, listRevision } from "./document-view-state";

export function DocumentListView({ items, hrefFor, onOpen }: {
  items: DocumentSummary[]; hrefFor: (id: string) => string; onOpen: (id: string) => void;
}) {
  return <table className="documents-table"><caption className="sr-only">등록 문서 · 최근 수정순</caption>
    <thead><tr><th scope="col">문서 제목</th><th scope="col">답변 사용</th><th scope="col">수정 상태</th><th scope="col">최근 수정</th></tr></thead>
    <tbody>{items.map(item => { const revision = listRevision(item); return <tr key={item.id}>
      <th scope="row"><Link data-document-id={item.id} href={hrefFor(item.id)} onClick={event => {
        if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault(); onOpen(item.id);
      }}>{revision.title}</Link>
        <p className="documents-list-revision">{item.published ? item.withdrawn ? "마지막 게시본" : "현재 게시본" : "저장된 초안"} · v{revision.revision_number}{revision.owner_department ? ` · ${revision.owner_department}` : ""}</p>
        {item.published && item.draft.title !== revision.title && <p className="documents-draft-title">수정 초안 제목: {item.draft.title}</p>}</th>
      <td className="documents-table-eligibility" data-label="답변 사용"><span className={`documents-status documents-status-${item.status}`}>{eligibilityLabel(item.eligibility)}</span></td>
      <td className="documents-table-changes" data-label="수정 상태">{hasDraftChanges(item) ? <span className="documents-change-badge">수정 초안 있음</span> : item.published ? "게시본과 동일" : "게시 전"}</td>
      <td className="documents-table-updated" data-label="최근 수정"><time dateTime={item.updated_at}>{item.updated_at.slice(0, 10)}</time></td>
    </tr>; })}</tbody></table>;
}
