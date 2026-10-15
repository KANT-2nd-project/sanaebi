"use client";

import dynamic from "next/dynamic";
import { useDeferredValue, useRef, useState, type ReactNode } from "react";
import type { ICommand } from "@uiw/react-md-editor";
import { MarkdownContent } from "../../components/markdown-content";
import { insertMarkdown, type MarkdownAction } from "./markdown-edit";

const MDEditor = dynamic(() => import("@uiw/react-md-editor/nohighlight"), { ssr: false,
  loading: () => <p role="status">편집기를 준비하는 중…</p> });
const tools: { action: MarkdownAction; label: string; shortcut?: string }[] = [
  { action: "heading", label: "제목 H2" }, { action: "bold", label: "굵게", shortcut: "ctrlcmd+b" },
  { action: "italic", label: "기울임", shortcut: "ctrlcmd+i" }, { action: "bullet", label: "글머리 목록" },
  { action: "number", label: "번호 목록" }, { action: "quote", label: "인용" },
  { action: "link", label: "링크", shortcut: "ctrlcmd+k" }, { action: "code", label: "코드 블록" },
];
const limitMessage = "50,000자를 초과하는 편집은 적용하지 않았습니다. 내용을 줄여주세요.";

export function MarkdownEditor({ id, value, title, titleInput, bodyFeedback, onChange, disabled, error, describedBy }: {
  id: string; value: string; title: string; titleInput: ReactNode; bodyFeedback: ReactNode;
  onChange: (value: string) => void; disabled: boolean; error?: string; describedBy: string;
}) {
  const [tab, setTab] = useState<"edit" | "preview">("edit");
  const activeTab = error ? "edit" : tab;
  const [toolError, setToolError] = useState("");
  const composing = useRef(false);
  const editTabRef = useRef<HTMLButtonElement>(null);
  const previewTabRef = useRef<HTMLButtonElement>(null);
  const preview = useDeferredValue(value);
  const commands: ICommand[] = tools.map(tool => ({
    name: tool.action, keyCommand: tool.action, shortcuts: tool.shortcut,
    icon: <span>{tool.label}</span>, buttonProps: { disabled, "aria-label": tool.label, title: tool.label },
    execute(state, api) {
      if (api.textArea.disabled || composing.current) return;
      const result = insertMarkdown(state.text, state.selection.start, state.selection.end, tool.action);
      if (result.overflow) { setToolError(limitMessage); api.textArea.focus({ preventScroll: true }); return; }
      setToolError("");
      const scroll = api.textArea.scrollTop;
      // Use the library's native edit transaction so formatting participates in undo/redo.
      api.setSelectionRange({ start: 0, end: state.text.length });
      api.replaceSelection(result.text);
      api.setSelectionRange({ start: result.start, end: result.end });
      api.textArea.scrollTop = scroll;
    },
  }));

  return <div className="document-markdown-editor" data-mode={activeTab}>
    <div className="document-markdown-tabs" role="tablist" aria-label="문서 편집 모드">
      {(["edit", "preview"] as const).map(mode => <button key={mode} ref={mode === "edit" ? editTabRef : previewTabRef}
        id={`${id}-${mode}-tab`} type="button" role="tab" aria-selected={activeTab === mode}
        aria-controls={`${id}-${mode}-panel`} tabIndex={activeTab === mode ? 0 : -1}
        className="documents-button documents-button-secondary" onClick={() => setTab(mode)}
        onKeyDown={event => {
          if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
          event.preventDefault();
          const next = error || event.key === "Home" ? "edit" : event.key === "End" ? "preview" : mode === "edit" ? "preview" : "edit";
          setTab(next);
          (next === "edit" ? editTabRef : previewTabRef).current?.focus();
        }}>{mode === "edit" ? "편집" : "미리보기"}</button>)}
    </div>
    <div className="document-markdown-columns">
      <section id={`${id}-edit-panel`} className="document-markdown-source" role="tabpanel" aria-label="Markdown 원문 편집"
        onChangeCapture={() => setTab("edit")}
        onKeyDownCapture={event => {
          if (!(event.target instanceof HTMLTextAreaElement)) return;
          const input = event.target;
          // The library installs a native key handler; stop it during IME composition.
          if (composing.current || event.nativeEvent.isComposing || event.keyCode === 229) { event.stopPropagation(); return; }
          if (event.ctrlKey && event.code === "KeyD") { event.preventDefault(); event.stopPropagation(); return; }
          if (event.key === "Enter") {
            const line = input.value.slice(0, input.selectionStart).split("\n").at(-1) ?? "";
            const marker = event.shiftKey ? "" : /^[-*] \[[ xX]\]/.test(line) ? "- [ ] " : /^[-*]\s/.test(line) ? `${line[0]} ` : /^\d+\.\s/.test(line) ? `${parseInt(line) + 1}. ` : "";
            if (input.value.length - (input.selectionEnd - input.selectionStart) + 1 + marker.length > 50_000) {
              event.preventDefault(); event.stopPropagation(); setToolError(limitMessage);
            }
          }
        }}>
        {titleInput}
        <label htmlFor={id} className="document-body-label">문서 원문 <span>(필수)</span></label>
        <div className="document-source-editor" data-color-mode="light">
          <MDEditor value={value} preview="edit" height="100%" minHeight={320} visibleDragbar={false}
            autoFocus={false} autoFocusEnd={false} defaultTabEnable enableScroll={false} overflow={false}
            commands={commands} extraCommands={[]}
            textareaProps={{ id, name: "body", required: true, maxLength: 50_000, disabled,
              "aria-invalid": Boolean(error), "aria-describedby": `${describedBy}${toolError ? ` ${id}-tool-error` : ""}`,
              onCompositionStart: () => { composing.current = true; }, onCompositionEnd: () => { composing.current = false; },
              onPaste: event => {
                const input = event.currentTarget;
                const inserted = event.clipboardData.getData("text/plain").replace(/\r\n?/g, "\n");
                if (input.value.length - (input.selectionEnd - input.selectionStart) + inserted.length > 50_000) {
                  event.preventDefault(); setToolError(limitMessage);
                }
              },
            }}
            onChange={(next, event) => {
              if (disabled) return;
              if ((next ?? "").length > 50_000) {
                if (event) event.target.value = value;
                setToolError(limitMessage); return;
              }
              setToolError(""); onChange(next ?? "");
            }} />
        </div>
        {toolError && <p id={`${id}-tool-error`} className="documents-field-error" role="alert">{toolError}</p>}
        {bodyFeedback}
      </section>
      <section id={`${id}-preview-panel`} className="document-markdown-preview" role="tabpanel" aria-label="문서 미리보기" tabIndex={0}>
        <div className="document-preview-content">
          <p className="document-preview-heading">미리보기</p>
          <h2 className="document-preview-title">{title.trim() ? title : "문서 제목을 입력하세요"}</h2>
          {preview.trim() ? <MarkdownContent text={preview} /> : <p className="documents-help">본문을 입력하면 여기에 미리보기가 표시됩니다.</p>}
        </div>
      </section>
    </div>
  </div>;
}
