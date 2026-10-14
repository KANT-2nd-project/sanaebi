import type { Metadata } from "next";
import { QuestionPanel } from "@/features/question/question-panel";

export const metadata: Metadata = {
  title: "질문 | 사내비",
  robots: { index: false, follow: false },
};

export default function ChatPage() {
  return <QuestionPanel />;
}
