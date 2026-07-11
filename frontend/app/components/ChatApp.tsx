"use client";

import { useEffect, useRef, useState } from "react";
import type {
  ChatErrorBody,
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
        const history = (await res.json()) as ChatTurn["message"][];
        if (!cancelled) {
          setTurns(history.map((message) => ({ message, payloads: [] })));
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
    return <p className="p-8 text-sm text-zinc-500">Loading...</p>;
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
        disabled={sending}
      />
      <div className="flex min-h-0 flex-1 flex-col">
        {activeConversation && (
          <div className="flex justify-end border-b border-zinc-200 px-4 py-2 dark:border-zinc-800">
            <ModelSelector
              models={models}
              selectedId={activeConversation.model}
              onSelect={changeModel}
              disabled={sending}
            />
          </div>
        )}
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
          {error && <p className="text-sm text-red-500">{error}</p>}
          <div ref={bottomRef} />
        </div>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            sendMessage(input);
          }}
          className="flex gap-2 border-t border-zinc-200 p-4 dark:border-zinc-800"
        >
          <input
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="Message the agent..."
            disabled={sending}
            className="flex-1 rounded-full border border-zinc-300 px-4 py-2 text-sm disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-900"
          />
          <button
            type="submit"
            disabled={sending || !input.trim()}
            className="rounded-full bg-foreground px-5 py-2 text-sm font-medium text-background disabled:opacity-50"
          >
            Send
          </button>
        </form>
      </div>
    </div>
  );
}
