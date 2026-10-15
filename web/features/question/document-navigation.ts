export type NavigationClick = {
  button: number;
  ctrlKey: boolean;
  metaKey: boolean;
  shiftKey: boolean;
  altKey: boolean;
};

/** Only intercept ordinary same-tab navigation; leave browser shortcuts intact. */
export function allowDocumentNavigation(
  click: NavigationClick,
  conversation: { turns: readonly unknown[]; activeTurnId: string | null },
  confirm: (message: string) => boolean,
  onNavigate?: () => void,
): boolean {
  if (click.button !== 0 || click.ctrlKey || click.metaKey || click.shiftKey || click.altKey) return true;
  if ((conversation.turns.length > 0 || conversation.activeTurnId !== null) && !confirm("문서 관리로 이동하면 대화 기록이 사라지고 진행 중 요청은 취소됩니다. 작성 중인 질문은 앱 안에서 이동해도 유지됩니다. 이동할까요?")) return false;
  // Cancel before route transition: a response can finish while confirm is open.
  onNavigate?.();
  return true;
}
