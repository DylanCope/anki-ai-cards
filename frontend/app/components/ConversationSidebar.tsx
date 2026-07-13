"use client";

import { useState } from "react";
import { Check, Pencil, Trash2, X } from "lucide-react";
import type { Conversation } from "@/app/lib/types";

interface Props {
  conversations: Conversation[];
  activeId: number | null;
  onSelect: (id: number) => void;
  onNewChat: () => void;
  onRename: (id: number, title: string) => void;
  onDelete: (id: number) => void;
  disabled: boolean;
  open: boolean;
  onClose: () => void;
}

export default function ConversationSidebar({
  conversations,
  activeId,
  onSelect,
  onNewChat,
  onRename,
  onDelete,
  disabled,
  open,
  onClose,
}: Props) {
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editValue, setEditValue] = useState("");

  function startEditing(conversation: Conversation) {
    setEditingId(conversation.id);
    setEditValue(conversation.title ?? "");
  }

  function commitEdit() {
    if (editingId === null) return;
    const title = editValue.trim();
    if (title) onRename(editingId, title);
    setEditingId(null);
  }

  function cancelEdit() {
    setEditingId(null);
  }

  function handleDelete(conversation: Conversation) {
    const label = conversation.title ?? "New conversation";
    if (window.confirm(`Delete "${label}"? This cannot be undone.`)) {
      onDelete(conversation.id);
    }
  }

  return (
    <>
      {open && (
        <div
          className="fixed inset-0 z-30 bg-black/50 md:hidden"
          onClick={onClose}
          aria-hidden="true"
        />
      )}
      <div
        className={`fixed inset-y-0 left-0 z-40 flex w-64 shrink-0 flex-col border-r border-border bg-surface transition-transform duration-200 ease-in-out md:static md:z-auto md:w-56 md:translate-x-0 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="p-3">
          <button
            type="button"
            onClick={onNewChat}
            disabled={disabled}
            className="w-full rounded-full bg-accent px-3 py-2 text-sm font-medium text-accent-foreground disabled:opacity-50"
          >
            + New chat
          </button>
        </div>
        <div className="min-h-0 flex-1 space-y-1 overflow-y-auto px-2 pb-3">
          {conversations.map((conversation) =>
            editingId === conversation.id ? (
              <div key={conversation.id} className="flex items-center gap-1 px-1 py-1">
                <input
                  autoFocus
                  value={editValue}
                  onChange={(event) => setEditValue(event.target.value)}
                  onBlur={commitEdit}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      commitEdit();
                    } else if (event.key === "Escape") {
                      event.preventDefault();
                      cancelEdit();
                    }
                  }}
                  className="w-full min-w-0 flex-1 rounded-lg border border-border bg-background px-2 py-1 text-sm"
                />
                <button
                  type="button"
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={commitEdit}
                  aria-label="Save title"
                  className="shrink-0 rounded-lg p-1 text-foreground/60 hover:bg-foreground/5 hover:text-foreground"
                >
                  <Check size={14} />
                </button>
                <button
                  type="button"
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={cancelEdit}
                  aria-label="Cancel rename"
                  className="shrink-0 rounded-lg p-1 text-foreground/60 hover:bg-foreground/5 hover:text-foreground"
                >
                  <X size={14} />
                </button>
              </div>
            ) : (
              <div
                key={conversation.id}
                className={`group flex items-center rounded-lg px-1 ${
                  conversation.id === activeId
                    ? "bg-accent/10 text-accent dark:bg-accent/20"
                    : "text-foreground/60 hover:bg-foreground/5"
                }`}
              >
                <button
                  type="button"
                  onClick={() => onSelect(conversation.id)}
                  className="min-w-0 flex-1 truncate px-2 py-2 text-left text-sm"
                >
                  {conversation.title ?? "New conversation"}
                </button>
                <button
                  type="button"
                  onClick={() => startEditing(conversation)}
                  disabled={disabled}
                  aria-label="Rename conversation"
                  className="shrink-0 rounded-lg p-1 opacity-0 hover:bg-foreground/10 group-hover:opacity-100 disabled:opacity-0"
                >
                  <Pencil size={14} />
                </button>
                <button
                  type="button"
                  onClick={() => handleDelete(conversation)}
                  disabled={disabled}
                  aria-label="Delete conversation"
                  className="shrink-0 rounded-lg p-1 opacity-0 hover:bg-foreground/10 group-hover:opacity-100 disabled:opacity-0"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            )
          )}
        </div>
      </div>
    </>
  );
}
