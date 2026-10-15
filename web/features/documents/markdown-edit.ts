export type MarkdownAction = "heading" | "bold" | "italic" | "bullet" | "number" | "quote" | "link" | "code";

export function insertMarkdown(text: string, start: number, end: number, action: MarkdownAction) {
  let from = start, to = end;
  let replacement: string, selectionStart: number, selectionEnd: number;
  if (["heading", "bullet", "number", "quote"].includes(action)) {
    from = start === 0 ? 0 : text.lastIndexOf("\n", start - 1) + 1;
    const last = end > start && text[end - 1] === "\n" ? end - 1 : end;
    const newline = text.indexOf("\n", last);
    to = newline < 0 ? text.length : newline;
    replacement = text.slice(from, to).split("\n").map((line, i) => {
      const prefix = action === "heading" ? "## " : action === "bullet" ? "- " : action === "quote" ? "> " : `${i + 1}. `;
      return prefix + line;
    }).join("\n");
    selectionStart = from;
    selectionEnd = from + replacement.length;
  } else {
    const selected = text.slice(start, end);
    if (action === "link") {
      const label = selected || "링크 설명";
      replacement = `[${label}](https://example.com)`;
      selectionStart = start + label.length + 3;
      selectionEnd = selectionStart + "https://example.com".length;
    } else if (action === "code") {
      const content = selected || "코드를 입력하세요";
      const fence = "`".repeat(Math.max(3, ...Array.from(content.matchAll(/`+/g), match => match[0].length + 1)));
      const prefix = start > 0 && text[start - 1] !== "\n" ? "\n" : "";
      const suffix = end < text.length && text[end] !== "\n" ? "\n" : "";
      replacement = `${prefix}${fence}\n${content}\n${fence}${suffix}`;
      selectionStart = start + prefix.length + fence.length + 1;
      selectionEnd = selectionStart + content.length;
    } else {
      const marker = action === "bold" ? "**" : "*";
      const content = selected || "강조할 내용";
      replacement = marker + content + marker;
      selectionStart = start + marker.length;
      selectionEnd = selectionStart + content.length;
    }
  }
  const next = text.slice(0, from) + replacement + text.slice(to);
  return next.length > 50_000 ? { text, start, end, overflow: true }
    : { text: next, start: selectionStart, end: selectionEnd, overflow: false };
}
