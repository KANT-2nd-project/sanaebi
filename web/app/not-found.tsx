import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "페이지를 찾을 수 없습니다 | 사내비" };

export default function NotFound() {
  return (
    <main className="mx-auto w-full max-w-3xl px-5 py-12 sm:px-8 sm:py-20">
      <p className="font-semibold text-action">사내비</p>
      <h1 className="mt-3 text-3xl font-semibold leading-snug break-keep">페이지를 찾을 수 없습니다</h1>
      <p className="mt-6 text-muted">주소가 변경되었거나 없는 페이지입니다. 홈이나 질문 화면으로 이동해주세요.</p>
      <nav aria-label="서비스로 돌아가기" className="mt-8 flex flex-wrap gap-4">
        <Link href="/" className="inline-flex min-h-12 items-center rounded-lg border border-current px-5 py-3 text-action">홈으로</Link>
        <Link href="/chat" className="inline-flex min-h-12 items-center rounded-lg bg-action px-5 py-3 font-medium text-white">질문하기</Link>
      </nav>
    </main>
  );
}
