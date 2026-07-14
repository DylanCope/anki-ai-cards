"use client";

import { useEffect, useRef, useState, type ChangeEvent } from "react";
import { Menu, Paperclip, X } from "lucide-react";
import type {
  ChatErrorBody,
  ChatHistoryResponseEntry,
  ChatPayload,
  ChatResponseBody,
  ChatTurn,
  Conversation,
  ImageAttachmentPayload,
  ModelInfo,
} from "@/app/lib/types";
import MessageBubble from "@/app/components/MessageBubble";
import AudioOptionsCard from "@/app/components/AudioOptionsCard";
import CardPayloadCard from "@/app/components/CardPayloadCard";
import ImageOptionsCard from "@/app/components/ImageOptionsCard";
import WorkflowLoadedCard from "@/app/components/WorkflowLoadedCard";
import ConversationSidebar from "@/app/components/ConversationSidebar";
import AiSettingsButton from "@/app/components/AiSettingsButton";
import WorkflowsButton from "@/app/components/WorkflowsButton";
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
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [pendingImage, setPendingImage] = useState<{
    imageId: number;
    previewUrl: string;
    fileName: string;
  } | null>(null);
  const [uploadingImage, setUploadingImage] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // Set right before the history-load effect calls setTurns, and consumed
  // (then reset) by the scroll effect below — lets it tell "a conversation's
  // history just loaded" (jump instantly) apart from "a new message arrived
  // in the conversation already on screen" (animate smoothly), instead of
  // always animating, which made every conversation open visibly scroll
  // from the top.
  const historyJustLoadedRef = useRef(false);

  const MAX_TEXTAREA_HEIGHT_PX = 200;

  const activeConversation = conversations.find((c) => c.id === conversationId) ?? null;

  const lastUserTurnIndex = (() => {
    for (let i = turns.length - 1; i >= 0; i--) {
      if (turns[i].message.role === "user") return i;
    }
    return -1;
  })();
  const turnAfterLastUserMessage =
    lastUserTurnIndex >= 0 ? turns[lastUserTurnIndex + 1] : undefined;
  const lastUserMessageEditable = !turnAfterLastUserMessage?.payloads.some(
    (payload) => payload.type === "card"
  );

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
          historyJustLoadedRef.current = true;
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
    const instant = historyJustLoadedRef.current;
    historyJustLoadedRef.current = false;
    bottomRef.current?.scrollIntoView({ behavior: instant ? "auto" : "smooth" });
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
      setSidebarOpen(false);
    } catch {
      setError("Could not start a new chat.");
    }
  }

  function selectConversation(id: number) {
    if (sending || id === conversationId) return;
    setError(null);
    setConversationId(id);
    setSidebarOpen(false);
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

  async function handleImageSelected(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;

    setError(null);
    setUploadingImage(true);
    const previewUrl = URL.createObjectURL(file);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetch("/api/images", { method: "POST", body: formData });
      if (res.status === 401) {
        URL.revokeObjectURL(previewUrl);
        setAuth("signed_out");
        return;
      }
      if (!res.ok) throw new Error(`Image upload failed (${res.status})`);
      const body = (await res.json()) as { image_id: number };
      setPendingImage((prev) => {
        if (prev) URL.revokeObjectURL(prev.previewUrl);
        return { imageId: body.image_id, previewUrl, fileName: file.name };
      });
    } catch {
      URL.revokeObjectURL(previewUrl);
      setError("Could not upload that image. Please try again.");
    } finally {
      setUploadingImage(false);
    }
  }

  function removePendingImage() {
    setPendingImage((prev) => {
      if (prev) URL.revokeObjectURL(prev.previewUrl);
      return null;
    });
  }

  // Picking an option (audio/image) appends to the composer instead of
  // sending immediately — with multiple choice cards showing at once (e.g.
  // pronunciation audio + a generated image in the same turn), auto-sending
  // on the first pick advanced the conversation before the second pick
  // could happen at all. Appending lets Dylan pick from several cards, then
  // send once.
  function appendPickToComposer(text: string) {
    setInput((prev) => (prev.trim() ? `${prev.trim()} ${text}` : text));
  }

  // Card creation/discard/preview are separate REST calls the pending-card
  // components make themselves (not new agent turns) — this just reflects
  // the resulting status back into local state so the card re-renders
  // without a full history reload.
  function updateTurnPayload(turnIndex: number, payloadIndex: number, updated: ChatPayload) {
    setTurns((prev) =>
      prev.map((turn, i) =>
        i !== turnIndex
          ? turn
          : {
              ...turn,
              payloads: turn.payloads.map((payload, j) => (j === payloadIndex ? updated : payload)),
            }
      )
    );
  }

  async function sendMessage(text: string) {
    const message = text.trim();
    if (!message || sending || conversationId === null) return;

    const imageId = pendingImage?.imageId;
    removePendingImage();
    setInput("");
    setError(null);
    setSending(true);
    setTurns((prev) => [...prev, { message: { role: "user", text: message }, payloads: [] }]);

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          conversation_id: conversationId,
          message,
          ...(imageId !== undefined ? { image_id: imageId } : {}),
        }),
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
      setTurns((prev) => {
        // The just-sent user turn was appended optimistically above, before
        // this attachment (if any) was known — attach it now so it renders
        // with the message it belongs to, not the assistant's reply.
        const withAttachment = body.attached_image
          ? prev.map((turn, i) =>
              i === prev.length - 1
                ? { ...turn, payloads: [...turn.payloads, body.attached_image!] }
                : turn
            )
          : prev;
        return [
          ...withAttachment,
          { message: { role: "assistant", text: body.reply }, payloads: body.payloads },
        ];
      });
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

  async function editMessage(index: number, text: string) {
    const message = text.trim();
    if (!message || sending || conversationId === null) return;

    setError(null);
    setSending(true);
    const previousTurns = turns;
    setTurns((prev) => [
      ...prev.slice(0, index),
      { message: { role: "user", text: message }, payloads: [] },
    ]);

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conversation_id: conversationId, message, edit: true }),
      });
      if (res.status === 401) {
        setAuth("signed_out");
        return;
      }
      if (res.status === 409) {
        setTurns(previousTurns);
        setError("Can't edit — a card was already created from this message.");
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
        setTurns(previousTurns);
        setError(errorMessage);
        return;
      }
      const body = (await res.json()) as ChatResponseBody;
      setTurns((prev) => [
        ...prev,
        { message: { role: "assistant", text: body.reply }, payloads: body.payloads },
      ]);
      const listRes = await fetch("/api/conversations");
      if (listRes.ok) {
        setConversations((await listRes.json()) as Conversation[]);
      }
    } catch {
      setTurns(previousTurns);
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
    <div className="flex min-h-0 w-full flex-1">
      <ConversationSidebar
        conversations={conversations}
        activeId={conversationId}
        onSelect={selectConversation}
        onNewChat={startNewChat}
        onRename={renameConversation}
        onDelete={deleteConversation}
        disabled={sending}
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />
      <div className="flex min-h-0 flex-1 flex-col">
        <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setSidebarOpen(true)}
              aria-label="Open conversation list"
              className="rounded-lg p-1.5 text-foreground/60 hover:bg-foreground/5 hover:text-foreground md:hidden"
            >
              <Menu size={20} />
            </button>
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent font-jp text-base leading-none font-bold whitespace-nowrap text-accent-foreground">
              暗助
            </div>
            <div className="leading-tight">
              <p className="text-sm font-bold text-foreground">Anjo</p>
              <p className="text-xs text-foreground/50">Anki Assistant</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {activeConversation && (
              <AiSettingsButton
                models={models}
                selectedId={activeConversation.model}
                onSelect={changeModel}
                disabled={sending}
              />
            )}
            <WorkflowsButton />
            <ThemeToggle />
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-6">
          <div className="mx-auto flex w-full max-w-3xl flex-col space-y-4">
            {turns.map((turn, index) => {
              const imageAttachment = turn.payloads.find(
                (payload): payload is ImageAttachmentPayload =>
                  payload.type === "image_attachment"
              );
              return (
                <div key={index}>
                  <MessageBubble
                    message={turn.message}
                    isLastUserMessage={index === lastUserTurnIndex}
                    editable={lastUserMessageEditable}
                    onSave={(text) => editMessage(index, text)}
                    imageAttachment={imageAttachment}
                  />
                  {turn.payloads.map((payload, payloadIndex) => {
                    // Rendered inside MessageBubble above instead, alongside
                    // the message it was attached to.
                    if (payload.type === "image_attachment") return null;
                    if (payload.type === "audio_options") {
                      return (
                        <AudioOptionsCard
                          key={payloadIndex}
                          payload={payload}
                          onPick={appendPickToComposer}
                          disabled={sending}
                        />
                      );
                    }
                    if (payload.type === "image_options") {
                      return (
                        <ImageOptionsCard
                          key={payloadIndex}
                          payload={payload}
                          onPick={appendPickToComposer}
                          disabled={sending}
                        />
                      );
                    }
                    if (payload.type === "workflow_loaded") {
                      return <WorkflowLoadedCard key={payloadIndex} payload={payload} />;
                    }
                    return (
                      <CardPayloadCard
                        key={payloadIndex}
                        payload={payload}
                        onRequestChange={setInput}
                        onUpdatePayload={(updated) =>
                          updateTurnPayload(index, payloadIndex, updated)
                        }
                        disabled={sending}
                      />
                    );
                  })}
                </div>
              );
            })}
            {sending && <TypingIndicator />}
            <div ref={bottomRef} />
          </div>
        </div>
        <div className="border-t border-border">
          <form
            onSubmit={(event) => {
              event.preventDefault();
              sendMessage(input);
            }}
            className="mx-auto flex w-full max-w-3xl flex-col gap-2 p-4"
          >
            {pendingImage && (
              <div className="flex items-center gap-2 self-start rounded-lg border border-border bg-surface p-2">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={pendingImage.previewUrl}
                  alt=""
                  className="h-12 w-12 rounded object-cover"
                />
                <span className="max-w-[10rem] truncate text-xs text-foreground/60">
                  {pendingImage.fileName}
                </span>
                <button
                  type="button"
                  onClick={removePendingImage}
                  aria-label="Remove attached image"
                  className="rounded-full p-1 text-foreground/50 hover:bg-foreground/10 hover:text-foreground"
                >
                  <X size={14} />
                </button>
              </div>
            )}
            <div className="flex gap-2">
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                onChange={handleImageSelected}
                className="hidden"
              />
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={sending || uploadingImage}
                aria-label="Attach an image"
                className="self-end rounded-lg p-2 text-foreground/60 hover:bg-foreground/5 hover:text-foreground disabled:opacity-50"
              >
                <Paperclip size={20} />
              </button>
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
                className="flex-1 resize-none overflow-y-auto rounded-lg border border-border bg-surface px-4 py-2 text-base disabled:opacity-50 md:text-sm"
              />
              <button
                type="submit"
                disabled={sending || !input.trim()}
                className="self-end rounded-full bg-accent px-5 py-2 text-sm font-medium text-accent-foreground disabled:opacity-50"
              >
                Send
              </button>
            </div>
          </form>
        </div>
      </div>
      {error && <Toast message={error} onDismiss={() => setError(null)} />}
    </div>
  );
}
