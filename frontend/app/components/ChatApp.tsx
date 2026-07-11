"use client";

import { useEffect, useRef, useState } from "react";
import type {
  ChatErrorBody,
  ChatHistoryResponseEntry,
  ChatResponseBody,
  ChatTurn,
  Conversation,
  ModelInfo,
} from "@/app/lib/types";
import MessageBubble from "@/app/components/MessageBubble";
import AudioOptionsCard from "@/app/components/AudioOptionsCard";
import CardPayloadCard from "@/app/components/CardPayloadCard";
import ConversationSidebar from "@/app/components/ConversationSidebar";
import ModelSelector from "@/app/components/ModelSelector";
import SignIn from "@/app/components/SignIn";
import ThemeToggle from "@/app/components/ThemeToggle";
import TypingIndicator from "@/app/components/TypingIndicator";
import Toast from "@/app/components/Toast";

type AuthState = "checking" | "signed_out" | "signed_in";

export default function ChatApp() {
  const [auth, setAuth] = useState<AuthState>("checking");
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const MAX_TEXTAREA_HEIGHT_PX = 200;

  const activeConversation = conversations.find((c) => c.id === conversationId) ?? null;

  // Bootstrap: load the model catalogue and conversation list, then open
  // the most recently updated conversation (or create a fresh one if this
  // account has none yet).
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [conversationsRes, modelsRes] = await Promise.all([
          fetch("/api/conversations"),
          fetch("/api/models"),
        ]);
        if (conversationsRes.status === 401 || modelsRes.status === 401) {
          if (!cancelled) setAuth("signed_out");
          return;
        }
        if (!conversationsRes.ok) {
          throw new Error(`Conversation list request failed (${conversationsRes.status})`);
        }
        if (!modelsRes.ok) throw new Error(`Model list request failed (${modelsRes.status})`);
        let list = (await conversationsRes.json()) as Conversation[];
        const modelList = (await modelsRes.json()) as ModelInfo[];
        if (list.length === 0) {
          const created = await fetch("/api/conversations", { method: "POST" });
          list = [(await created.json()) as Conversation];
        }
        if (!cancelled) {
          setConversations(list);
          setModels(modelList);
          setConversationId(list[0].id);
          setAuth("signed_in");
        }
      } catch {
        if (!cancelled) setError("Could not reach the server.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Load the active conversation's transcript whenever it changes.
  useEffect(() => {
    if (conversationId === null) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`/api/chat/history?conversation_id=${conversationId}`);
        if (res.status === 401) {
          if (!cancelled) setAuth("signed_out");
          return;
        }
        if (!res.ok) throw new Error(`History request failed (${res.status})`);
        const history = (await res.json()) as ChatHistoryResponseEntry[];
        if (!cancelled) {
          setTurns(
            history.map((entry) => ({
              message: { role: entry.role, text: entry.text },
              payloads: entry.payloads,
            }))
          );
        }
      } catch {
        if (!cancelled) setError("Could not reach the server.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [conversationId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  // Auto-resize the composer to fit its content, up to a max height.
  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, MAX_TEXTAREA_HEIGHT_PX)}px`;
  }, [input]);

  async function startNewChat() {
    if (sending) return;
    setError(null);
    try {
      const res = await fetch("/api/conversations", { method: "POST" });
      if (res.status === 401) {
        setAuth("signed_out");
        return;
      }
      const created = (await res.json()) as Conversation;
      setConversations((prev) => [created, ...prev]);
      setConversationId(created.id);
      setTurns([]);
    } catch {
      setError("Could not start a new chat.");
    }
  }

  function selectConversation(id: number) {
    if (sending || id === conversationId) return;
    setError(null);
    setConversationId(id);
  }

  async function renameConversation(id: number, title: string) {
    if (sending) return;
    setError(null);
    try {
      const res = await fetch(`/api/conversations/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      });
      if (res.status === 401) {
        setAuth("signed_out");
        return;
      }
      if (!res.ok) throw new Error(`Rename failed (${res.status})`);
      const updated = (await res.json()) as Conversation;
      setConversations((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));
    } catch {
      setError("Could not rename the conversation.");
    }
  }

  async function deleteConversation(id: number) {
    if (sending) return;
    setError(null);
    try {
      const res = await fetch(`/api/conversations/${id}`, { method: "DELETE" });
      if (res.status === 401) {
        setAuth("signed_out");
        return;
      }
      if (!res.ok) throw new Error(`Delete failed (${res.status})`);
      const remaining = conversations.filter((c) => c.id !== id);
      setConversations(remaining);
      if (id === conversationId) {
        if (remaining.length > 0) {
          setConversationId(remaining[0].id);
        } else {
          await startNewChat();
        }
      }
    } catch {
      setError("Could not delete the conversation.");
    }
  }

  async function changeModel(modelId: string) {
    if (conversationId === null || sending) return;
    setError(null);
    try {
      const res = await fetch(`/api/conversations/${conversationId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: modelId }),
      });
      if (res.status === 401) {
        setAuth("signed_out");
        return;
      }
      if (!res.ok) throw new Error(`Model update failed (${res.status})`);
      const updated = (await res.json()) as Conversation;
      setConversations((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));
    } catch {
      setError("Could not change the model.");
    }
  }

  async function sendMessage(text: string) {
    const message = text.trim();
    if (!message || sending || conversationId === null) return;

    setInput("");
    setError(null);
    setSending(true);
    setTurns((prev) => [...prev, { message: { role: "user", text: message }, payloads: [] }]);

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conversation_id: conversationId, message }),
      });
      if (res.status === 401) {
        setAuth("signed_out");
        return;
      }
      if (!res.ok) {
        let errorMessage = "Something went wrong sending that message. Please try again.";
        try {
          const errorBody = (await res.json()) as ChatErrorBody;
          if (errorBody.detail?.bug_report_id) {
            errorMessage = `Something went wrong — bug report #${errorBody.detail.bug_report_id} filed.`;
          } else if (errorBody.detail?.error) {
            errorMessage = errorBody.detail.error;
          }
        } catch {}
        setError(errorMessage);
        return;
      }
      const body = (await res.json()) as ChatResponseBody;
      setTurns((prev) => [
        ...prev,
        { message: { role: "assistant", text: body.reply }, payloads: body.payloads },
      ]);
      // The turn may have set the conversation's title (from its first
      // message) and bumped its updated_at — refresh the list so the
      // sidebar reflects that without a full reload.
      const listRes = await fetch("/api/conversations");
      if (listRes.ok) {
        setConversations((await listRes.json()) as Conversation[]);
      }
    } catch {
      setError("Something went wrong sending that message. Please try again.");
    } finally {
      setSending(false);
    }
  }

  if (auth === "checking") {
    return <p className="p-8 text-sm text-foreground/50">Loading...</p>;
  }

  if (auth === "signed_out") {
    return <SignIn />;
  }

  return (
    <div className="flex min-h-0 w-full max-w-5xl flex-1">
      <ConversationSidebar
        conversations={conversations}
        activeId={conversationId}
        onSelect={selectConversation}
        onNewChat={startNewChat}
        onRename={renameConversation}
        onDelete={deleteConversation}
        disabled={sending}
      />
      <div className="flex min-h-0 flex-1 flex-col">
        <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent font-jp text-lg font-bold text-accent-foreground">
              語
            </div>
            <div className="leading-tight">
              <p className="text-sm font-bold text-foreground">anki-ai-cards</p>
              <p className="text-xs text-foreground/50">Japanese lessons → Anki cards</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {activeConversation && (
              <ModelSelector
                models={models}
                selectedId={activeConversation.model}
                onSelect={changeModel}
                disabled={sending}
              />
            )}
            <ThemeToggle />
          </div>
        </div>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-6">
          {turns.map((turn, index) => (
            <div key={index}>
              <MessageBubble message={turn.message} />
              {turn.payloads.map((payload, payloadIndex) =>
                payload.type === "audio_options" ? (
                  <AudioOptionsCard
                    key={payloadIndex}
                    payload={payload}
                    onPick={sendMessage}
                    disabled={sending}
                  />
                ) : (
                  <CardPayloadCard
                    key={payloadIndex}
                    payload={payload}
                    onRequestChange={setInput}
                    disabled={sending}
                  />
                )
              )}
            </div>
          ))}
          {sending && <TypingIndicator />}
          <div ref={bottomRef} />
        </div>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            sendMessage(input);
          }}
          className="flex gap-2 border-t border-border p-4"
        >
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key !== "Enter" || event.shiftKey) return;
              // Skip submission while an IME composition is in progress —
              // Enter also confirms kana->kanji conversion.
              if (event.nativeEvent.isComposing || event.keyCode === 229) return;
              event.preventDefault();
              sendMessage(input);
            }}
            placeholder="Message the agent..."
            disabled={sending}
            rows={1}
            style={{ maxHeight: MAX_TEXTAREA_HEIGHT_PX }}
            className="flex-1 resize-none overflow-y-auto rounded-lg border border-border bg-surface px-4 py-2 text-sm disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={sending || !input.trim()}
            className="self-end rounded-full bg-accent px-5 py-2 text-sm font-medium text-accent-foreground disabled:opacity-50"
          >
            Send
          </button>
        </form>
      </div>
      {error && <Toast message={error} onDismiss={() => setError(null)} />}
    </div>
  );
}
