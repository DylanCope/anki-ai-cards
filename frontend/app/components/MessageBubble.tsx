import type { ChatHistoryEntry } from "@/app/lib/types";

export default function MessageBubble({ message }: { message: ChatHistoryEntry }) {
  const isUser = message.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[80%] whitespace-pre-wrap rounded-2xl px-4 py-2 text-sm ${
          isUser
            ? "bg-foreground text-background"
            : "bg-zinc-100 text-foreground dark:bg-zinc-800"
        }`}
      >
        {message.text}
      </div>
    </div>
  );
}
