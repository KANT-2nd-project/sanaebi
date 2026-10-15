import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkBreaks from "remark-breaks";

function safeLink(value: string) {
  if (!/^https?:\/\//i.test(value)) return "";
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : "";
  } catch {
    return "";
  }
}

const components: Components = {
  h1: ({ children }) => <h3>{children}</h3>,
  h2: ({ children }) => <h3>{children}</h3>,
  h3: ({ children }) => <h3>{children}</h3>,
  h4: ({ children }) => <h4>{children}</h4>,
  h5: ({ children }) => <h5>{children}</h5>,
  h6: ({ children }) => <h6>{children}</h6>,
  a: ({ href, children }) => href
    ? <a href={href} target="_blank" rel="noopener noreferrer">{children}<span className="sr-only"> (새 탭에서 열림)</span></a>
    : <>{children}</>,
  img: ({ alt }) => <>{alt || ""}</>,
  pre: ({ children }) => <pre tabIndex={0} aria-label="코드 블록">{children}</pre>,
  table: ({ children }) => <div className="answer-table-scroll" tabIndex={0} role="region" aria-label="답변 표"><table>{children}</table></div>,
};

export function AnswerMarkdown({ text }: { text: string }) {
  return (
    <div className="answer-text">
      <Markdown remarkPlugins={[remarkGfm, remarkBreaks]} components={components}
        skipHtml urlTransform={safeLink}>{text}</Markdown>
    </div>
  );
}
