import type { Metadata } from "next";
import { Suspense } from "react";
import { DocumentPanel } from "../../../features/documents/document-panel";

export const metadata: Metadata = {
  title: "문서 관리 | 사내비",
  description: "사내비 문서 초안과 게시 상태를 관리합니다.",
  robots: { index: false, follow: false },
};

export default function DocumentsPage() {
  return <Suspense fallback={<main className="documents-page"><p className="documents-loading">문서 관리 화면을 준비하는 중…</p></main>}>
    <DocumentPanel />
  </Suspense>;
}
