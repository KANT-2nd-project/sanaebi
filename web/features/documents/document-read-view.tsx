"use client";
import type { DocumentDetail } from "../../lib/api/documents";
import { eligibilityLabel, hasDraftChanges, reviewLabel, selectedRevision, type DocumentView } from "./document-view-state";

export function DocumentReadView({ detail, revision, busy, onRevision, onEdit, onPublish, onWithdraw }: {
  detail: DocumentDetail; revision: DocumentView["revision"]; busy: boolean;
  onRevision: (revision: "draft" | "published") => void; onEdit: () => void; onPublish: () => void; onWithdraw: () => void;
}) {
  const selected = selectedRevision(detail, revision);
  const isPublished = selected.id === detail.published?.id;
  const changes = hasDraftChanges(detail);
  return <>
    <div className="documents-reader-heading">
      <div><p className="documents-eyebrow">{isPublished ? detail.withdrawn ? "마지막 게시본" : "현재 게시본" : "저장된 초안"} · v{selected.revision_number}</p>
        <h2 id="document-editor-title" tabIndex={-1}>{selected.title}</h2></div>
      <button type="button" className="documents-button documents-button-secondary" disabled={busy} onClick={onEdit}>초안 편집</button>
    </div>
    <div className="documents-reader-status"><span className="documents-status">{eligibilityLabel(detail.eligibility)}</span>
      {changes && <span className="documents-status documents-status-draft">수정 초안 있음</span>}</div>
    {changes && <div className="documents-revision-tabs" role="group" aria-label="읽을 개정 선택">
      <button type="button" aria-pressed={isPublished} disabled={busy} onClick={() => onRevision("published")}>{detail.withdrawn ? "마지막 게시본" : "현재 게시본"} v{detail.published!.revision_number}</button>
      <button type="button" aria-pressed={!isPublished} disabled={busy} onClick={() => onRevision("draft")}>수정 초안 v{detail.draft.revision_number}</button>
    </div>}
    {!isPublished && <p className="documents-help">이 초안은 아직 답변에 사용되지 않습니다.{detail.published && !detail.withdrawn ? " 기존 게시본은 유지됩니다." : ""}</p>}
    {detail.eligibility === "scheduled" && <p className="documents-help">게시본 시행일 {detail.published?.effective_from}부터 답변 근거가 됩니다. 다른 게시본으로 자동 교체하는 예약 기능은 아닙니다.</p>}
    <div className="documents-reader-layout">
      <article className="documents-reader-body" aria-label="선택한 개정의 원문"><p className="documents-help">검수: {reviewLabel(selected.metadata?.review_status)} · 게시는 사람의 검수 승인을 뜻하지 않습니다.</p>
        <div className="documents-plain-text">{selected.body}</div></article>
      <aside className="documents-reader-metadata" aria-label="선택한 개정 정보">
        <h3>이 개정의 정보</h3><dl><dt>개정</dt><dd>v{selected.revision_number}</dd><dt>시행일</dt><dd>{selected.effective_from || "없음"}</dd>
          <dt>담당 부서</dt><dd>{selected.owner_department || "미지정"}</dd><dt>출처 이름</dt><dd>{selected.source_label || "없음"}</dd>
          {selected.source_url && <><dt>출처 주소</dt><dd>{selected.source_url}</dd></>}</dl>
        <details><summary>출처와 검수</summary><p>이 개정의 검수: {reviewLabel(selected.metadata?.review_status)}</p>
          <p>분류: {selected.metadata?.category || "없음"}</p><p>출처 ID: {selected.metadata?.source_ids.join(", ") || "없음"}</p>
          <p>정책 결정 ID: {selected.metadata?.policy_decision_ids.join(", ") || "없음"}</p>
          {detail.provenance && <><h4>최초 이관 정보</h4><p>원본 ID: {detail.provenance.source_document_id}</p><p>원본 버전: {selected.metadata?.source_version || "없음"}</p></>}
        </details><details><summary>기술 정보</summary><p>관리 ID: {detail.id}</p><p>개정 ID: {selected.id}</p><p>본문 해시: {selected.content_hash}</p></details>
      </aside>
    </div>
    <div className="documents-publication-actions"><div><strong>저장된 초안 v{detail.draft.revision_number}</strong>
      <p className="documents-help">{detail.withdrawn ? "다시 게시하면 시행일 조건에 따라 답변에 사용됩니다." : changes ? "게시하면 현재 게시본을 이 초안으로 교체합니다." : detail.published ? "현재 게시본과 같은 개정입니다." : "게시하면 시행일 조건에 따라 다음 질문의 답변 근거가 됩니다."}</p></div>
      <div className="documents-editor-actions">
        {detail.published && !detail.withdrawn && <button type="button" className="documents-button documents-button-danger" disabled={busy} onClick={onWithdraw}>사용 중단</button>}
        <button type="button" className="documents-button documents-button-primary" disabled={busy || Boolean(detail.published && !changes && !detail.withdrawn)} onClick={onPublish}>
          {detail.withdrawn ? "다시 게시" : detail.published && !changes ? "게시 중인 개정" : "초안 게시 검토"}</button>
      </div></div>
  </>;
}
