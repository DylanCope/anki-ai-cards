"use client";

import { useEffect, useRef, useState } from "react";
import { Pencil } from "lucide-react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatHistoryEntry } from "@/app/lib/types";

const EDIT_TEXTAREA_MAX_HEIGHT_PX = 200;

const markdownComponents: Components = {
  p: ({ children }) => <p className="my-1 first:mt-0 last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="my-1 list-disc pl-5">{children}</ul>,
  ol: ({ children }) => <ol className="my-1 list-decimal pl-5">{children}</ol>,
  li: ({ children }) => <li className="my-0.5">{children}</li>,
  h1: ({ children }) => <h1 className="mt-2 mb-1 text-lg font-semibold">{children}</h1>,
  h2: ({ children }) => <h2 className="mt-2 mb-1 text-base font-semibold">{children}</h2>,
  h3: ({ children }) => <h3 className="mt-2 mb-1 text-sm font-semibold">{children}</h3>,
  a: ({ children, href }) => (
    <a href={href} target="_blank" rel="noreferrer" className="underline underline-offset-2">
      {children}
    </a>
  ),
  code: ({ children, className }) => {
    const isBlock = /language-/.test(className ?? "");
    if (isBlock) {
      return <code className={className}>{children}</code>;
    }
    return (
      <code className="rounded bg-black/10 px-1 py-0.5 text-[0.85em] dark:bg-white/10">
        {children}
      </code>
    );
  },
  pre: ({ children }) => (
    <pre className="my-2 overflow-x-auto rounded-lg bg-black/10 p-2 text-[0.85em] dark:bg-white/10">
      {children}
    </pre>
  ),
  blockquote: ({ children }) => (
    <blockquote className="my-1 border-l-2 border-current/30 pl-2 italic">
      {children}
    </blockquote>
  ),
  table: ({ children }) => (
    <div className="my-2 overflow-x-auto">
      <table className="border-collapse text-left">{children}</table>
    </div>
  ),
  th: ({ children }) => (
    <th className="border border-current/20 px-2 py-1 font-semibold">{children}</th>
  ),
  td: ({ children }) => <td className="border border-current/20 px-2 py-1">{children}</td>,
};

interface Props {
  message: ChatHistoryEntry;
  isLastUserMessage?: boolean;
  editable?: boolean;
  onSave?: (text: string) => void;
}

export default function MessageBubble({
  message,
  isLastUserMessage = false,
  editable = false,
  onSave,
}: Props) {
  const isUser = message.role === "user";
  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState(message.text);
  const [showTooltip, setShowTooltip] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea || !isEditing) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, EDIT_TEXTAREA_MAX_HEIGHT_PX)}px`;
  }, [draft, isEditing]);

  function startEditing() {
    setDraft(message.text);
    setIsEditing(true);
  }

  function cancelEditing() {
    setIsEditing(false);
    setDraft(message.text);
  }

  function saveEditing() {
    const trimmed = draft.trim();
    if (!trimmed) return;
    setIsEditing(false);
    onSave?.(trimmed);
  }

  const showPencil = isUser && isLastUserMessage;

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`group relative max-w-[80%] rounded-xl px-4 py-2 text-sm ${
          isUser
            ? "bg-accent text-accent-foreground"
            : "bg-surface text-foreground border border-border"
        }`}
      >
        {showPencil && !isEditing && (
          <div className="absolute -top-2 -right-2">
            <button
              type="button"
              aria-label={
                editable
                  ? "Edit message"
                  : "Can't edit — a card was already created from this message"
              }
              onClick={editable ? startEditing : undefined}
              onMouseEnter={() => setShowTooltip(true)}
              onMouseLeave={() => setShowTooltip(false)}
              className={`rounded-full border border-border bg-surface p-1 opacity-0 shadow-sm transition-opacity group-hover:opacity-100 ${
                editable
                  ? "cursor-pointer text-foreground/60 hover:text-foreground"
                  : "cursor-default text-foreground/30"
              }`}
            >
              <Pencil size={12} />
            </button>
            {showTooltip && !editable && (
              <div className="absolute right-0 top-full z-10 mt-1 w-48 rounded-lg border border-border bg-surface px-2 py-1 text-xs text-foreground shadow-lg">
                Can&apos;t edit — a card was already created from this message.
              </div>
            )}
          </div>
        )}
        {isEditing ? (
          <div className="flex flex-col gap-2">
            <textarea
              ref={textareaRef}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Escape") {
                  event.preventDefault();
                  cancelEditing();
                  return;
                }
                if (event.key !== "Enter" || event.shiftKey) return;
                // Skip submission while an IME composition is in progress —
                // Enter also confirms kana->kanji conversion.
                if (event.nativeEvent.isComposing || event.keyCode === 229) return;
                event.preventDefault();
                saveEditing();
              }}
              rows={1}
              autoFocus
              style={{ maxHeight: EDIT_TEXTAREA_MAX_HEIGHT_PX }}
              className="w-full resize-none overflow-y-auto rounded-lg border border-accent-foreground/30 bg-accent-foreground/10 px-2 py-1 text-sm text-accent-foreground outline-none"
            />
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={cancelEditing}
                className="rounded-lg px-2 py-1 text-xs font-medium hover:bg-accent-foreground/10"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={saveEditing}
                disabled={!draft.trim()}
                className="rounded-lg bg-accent-foreground/20 px-2 py-1 text-xs font-medium hover:bg-accent-foreground/30 disabled:opacity-50"
              >
                Save
              </button>
            </div>
          </div>
        ) : (
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
            {message.text}
          </ReactMarkdown>
        )}
      </div>
    </div>
  );
}
