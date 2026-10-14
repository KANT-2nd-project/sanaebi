import type { Metadata } from "next";
import Link from "next/link";
import { QuestionPanel } from "@/features/question/question-panel";

export const metadata: Metadata = {
  title: "질문 | 사내비",
  robots: { index: false, follow: false },
};

export default function ChatPage() {
  return (
    <>
      <header className="border-b border-boundary bg-surface">
        <nav aria-label="주 메뉴" className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-5 py-4">
          <Link href="/" className="inline-flex min-h-12 items-center text-2xl font-semibold text-action">사내비</Link>
          <a href="#usage" className="inline-flex min-h-12 items-center text-sm text-muted underline underline-offset-4">사용 안내</a>
        </nav>
      </header>
      <main className="mx-auto w-full max-w-[760px] px-5 py-9 sm:py-14">
        <h1 className="text-[26px] font-semibold leading-snug sm:text-[32px]">
          회사 규정과 업무 절차를 물어보세요.
        </h1>
        <p className="mt-4 text-muted">
          현재는 입력한 질문을 그대로 돌려주는 연결 확인 단계입니다. 실제 규정 답변은 아직 제공하지 않습니다.
        </p>
        <QuestionPanel />
        <section id="usage" aria-labelledby="usage-title" className="mt-8 scroll-mt-6 border-t border-boundary pt-6">
          <h2 id="usage-title" className="text-lg font-semibold">사용 안내</h2>
          <p className="mt-3 text-sm text-muted">
            사내비는 회사 규정과 업무 절차 안내를 목표로 합니다. 실제 신청·승인이나 개인 기록 조회는 지원하지 않습니다.
          </p>
        </section>
      </main>
    </>
  );
}
