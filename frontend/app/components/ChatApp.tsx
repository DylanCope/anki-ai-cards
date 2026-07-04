"use client";

import { useEffect, useRef, useState } from "react";
import type { ChatErrorBody, ChatResponseBody, ChatTurn } from "@/app/lib/types";
import MessageBubble from "@/app/components/MessageBubble";
import AudioOptionsCard from "@/app/components/AudioOptionsCard";
import CardPayloadCard from "@/app/components/CardPayloadCard";
import SignIn from "@/app/components/SignIn";

type AuthState = "checking" | "signed_out" | "signed_in";

export default function ChatApp() {
  const [auth, setAuth] = useState<AuthState>("checking");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/chat/history");
        if (res.status === 401) {
          if (!cancelled) setAuth("signed_out");
          return;
        }
        if (!res.ok) throw new Error(`History request failed (${res.status})`);
        const history = (await res.json()) as ChatTurn["message"][];
        if (!cancelled) {
          setTurns(history.map((message) => ({ message, payloads: [] })));
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

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  async function sendMessage(text: string) {
    const message = text.trim();
    if (!message || sending) return;

    setInput("");
    setError(null);
    setSending(true);
    setTurns((prev) => [...prev, { message: { role: "user", text: message }, payloads: [] }]);

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
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
    <div className="flex w-full max-w-2xl flex-1 flex-col">
      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-6">
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
  );
}
