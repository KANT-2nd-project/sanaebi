export default function Home() {
  return (
    <main className="mx-auto w-full max-w-3xl px-5 py-12 sm:px-8 sm:py-20">
      <p className="font-semibold text-action">사내비</p>
      <h1 className="mt-3 text-3xl font-semibold leading-snug">
        회사 규정과 업무 절차를 안내합니다.
      </h1>
      <p className="mt-6 text-muted">
        사내비는 회사 문서에 근거해 반복되는 업무 질문에 답하고,
        필요한 정보를 찾도록 돕는 서비스입니다.
      </p>
      <section aria-labelledby="scope-title" className="mt-8">
        <h2 id="scope-title" className="text-xl font-semibold">
          지원 범위
        </h2>
        <p className="mt-3 text-muted">
          규정과 절차 안내를 목표로 하며, 실제 신청·승인이나 개인 기록 조회는
          지원하지 않습니다. 현재 질문 기능은 입력한 내용을 그대로 돌려주는 연결 확인 단계이며, 실제 규정 답변은 준비 중입니다.
        </p>
      </section>
      <a
        href="/chat/"
        className="mt-8 inline-flex min-h-12 items-center rounded-lg bg-action px-5 py-3 font-medium text-white"
      >
        질문 화면으로 이동
      </a>
    </main>
  );
}
