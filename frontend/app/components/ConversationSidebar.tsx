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
    <div className="flex w-56 shrink-0 flex-col border-r border-zinc-200 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-950">
      <div className="p-3">
        <button
          type="button"
          onClick={onNewChat}
          disabled={disabled}
          className="w-full rounded-full bg-foreground px-3 py-2 text-sm font-medium text-background disabled:opacity-50"
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
                ? "bg-zinc-200 text-foreground dark:bg-zinc-800"
                : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-900"
            }`}
          >
            {conversation.title ?? "New conversation"}
          </button>
        ))}
      </div>
    </div>
  );
}
