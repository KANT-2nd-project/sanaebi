import type { Metadata } from "next";
import "./globals.css";
import { ChatDraftProvider } from "../features/question/chat-draft-provider";

export const metadata: Metadata = {
  title: "사내비 | 사내 지식 안내",
  description: "회사 규정과 업무 절차를 문서에 근거해 안내하는 사내비입니다.",
  robots: {
    index: false,
    follow: false,
  },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ko" className="h-full antialiased">
      <body className="min-h-full flex flex-col"><ChatDraftProvider>{children}</ChatDraftProvider></body>
    </html>
  );
}
