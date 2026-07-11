"use client";

import type { Conversation } from "@/app/lib/types";

interface Props {
  conversations: Conversation[];
  activeId: number | null;
  onSelect: (id: number) => void;
  onNewChat: () => void;
  disabled: boolean;
}

export default function ConversationSidebar({
  conversations,
  activeId,
  onSelect,
  onNewChat,
  disabled,
}: Props) {
  return (
    <div className="flex w-56 shrink-0 flex-col border-r border-border bg-surface">
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
        {conversations.map((conversation) => (
          <button
            key={conversation.id}
            type="button"
            onClick={() => onSelect(conversation.id)}
            className={`block w-full truncate rounded-lg px-3 py-2 text-left text-sm ${
              conversation.id === activeId
                ? "bg-accent/10 text-accent dark:bg-accent/20"
                : "text-foreground/60 hover:bg-foreground/5"
            }`}
          >
            {conversation.title ?? "New conversation"}
          </button>
        ))}
      </div>
    </div>
  );
}
