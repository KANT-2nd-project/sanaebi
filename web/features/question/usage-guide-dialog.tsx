"use client";

import { useEffect, useRef, type RefObject } from "react";

type UsageGuideDialogProps = {
  triggerRef: RefObject<HTMLButtonElement | null>;
  onClose: () => void;
};

export function UsageGuideDialog({ triggerRef, onClose }: UsageGuideDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const backdropPress = useRef(false);

  function isOutside(dialog: HTMLDialogElement, x: number, y: number) {
    const rect = dialog.getBoundingClientRect();
    return x < rect.left || x > rect.right || y < rect.top || y > rect.bottom;
  }

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const trigger = triggerRef.current;
    dialog.showModal();
    titleRef.current?.focus({ preventScroll: true });
    return () => {
      dialog.close();
      queueMicrotask(() => {
        // Strict Mode may reopen this same dialog before cleanup finishes.
        if (!dialog.open && trigger?.isConnected) trigger.focus({ preventScroll: true });
      });
    };
  }, [triggerRef]);

  return (
    <dialog ref={dialogRef} className="usage-guide-dialog" aria-labelledby="usage-guide-title"
      onPointerDown={event => {
        backdropPress.current = event.target === event.currentTarget &&
          isOutside(event.currentTarget, event.clientX, event.clientY);
      }}
      onPointerCancel={() => { backdropPress.current = false; }}
      onClick={event => {
        if (backdropPress.current && event.target === event.currentTarget &&
            isOutside(event.currentTarget, event.clientX, event.clientY)) onClose();
        backdropPress.current = false;
      }}
      onKeyDown={event => {
        // Keep keyboard navigation within the close control and scrollable body.
        if (event.key === "Tab") {
          event.preventDefault();
          const target = document.activeElement === closeRef.current ||
            (document.activeElement === titleRef.current && event.shiftKey)
            ? bodyRef.current : closeRef.current;
          target?.focus({ preventScroll: true });
        }
      }}
      onCancel={event => { event.preventDefault(); onClose(); }}>
      <header className="usage-guide-heading">
        <h2 ref={titleRef} id="usage-guide-title" tabIndex={-1}>사용 안내</h2>
        <button ref={closeRef} type="button" className="chat-button header-button" onClick={onClose}>닫기</button>
      </header>
      <div ref={bodyRef} className="usage-guide-body" tabIndex={0} role="region" aria-label="사용 안내 내용">
        <section>
          <h3>질문할 수 있는 내용</h3>
          <p>게시된 회사 문서를 바탕으로 회사 규정과 업무 절차를 안내합니다.</p>
        </section>
        <section>
          <h3>질문하는 방법</h3>
          <p>대상과 상황을 함께 적어주세요.</p>
          <p>예: “연차를 신청하려면 어떤 절차가 필요한가요?”</p>
        </section>
        <section>
          <h3>기억할 점</h3>
          <ul>
            <li>이전 메시지는 답변에 반영되지 않습니다. 질문마다 필요한 내용을 함께 적어주세요.</li>
            <li>페이지를 벗어나거나 새로고침하면 대화가 사라지고 진행 중인 요청은 취소됩니다.</li>
            <li>작성 중인 질문은 앱 안에서 이동해도 유지되며, 새로고침하거나 새 대화를 시작하면 지워집니다.</li>
            <li>질문을 보내면 입력창이 비워집니다. 답변을 기다리며 다음 질문을 작성할 수 있지만 전송은 답변이 끝난 뒤 가능합니다. 실패했을 때 입력창이 비어 있으면 보낸 입력을 복원하고, 작성 중인 내용이 있으면 유지합니다. 이미 보낸 질문은 페이지 이동 후 입력창에 복원되지 않습니다.</li>
            <li>실제 신청·승인·개인 기록 조회는 지원하지 않습니다.</li>
          </ul>
        </section>
      </div>
    </dialog>
  );
}
