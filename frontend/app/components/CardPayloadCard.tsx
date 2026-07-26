"use client";

import { Fragment, useState } from "react";
import { Loader2 } from "lucide-react";
import type { CardPayload, PendingCardPreview } from "@/app/lib/types";
import PendingCardPreviewModal from "@/app/components/PendingCardPreviewModal";

interface Props {
  payload: CardPayload;
  onRequestChange: (message: string) => void;
  onUpdatePayload: (payload: CardPayload) => void;
  disabled: boolean;
}

type PreviewSide = "front" | "back";
type PreviewWidth = "mobile" | "pc";

export default function CardPayloadCard({
  payload,
  onRequestChange,
  onUpdatePayload,
  disabled,
}: Props) {
  const fields = payload.fields ?? {};
  const status = payload.status ?? "created";

  const [preview, setPreview] = useState<PendingCardPreview | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewSide, setPreviewSide] = useState<PreviewSide>("front");
  const [previewWidth, setPreviewWidth] = useState<PreviewWidth>("pc");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [discarding, setDiscarding] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  async function openPreview() {
    if (preview) {
      setPreviewOpen(true);
      return;
    }
    if (payload.pending_card_id == null) return;
    setPreviewLoading(true);
    setPreviewError(null);
    try {
      const res = await fetch(`/api/pending-cards/${payload.pending_card_id}/preview`);
      if (!res.ok) throw new Error(`Preview request failed (${res.status})`);
      const data = (await res.json()) as PendingCardPreview;
      setPreview(data);
      setPreviewOpen(true);
    } catch {
      setPreviewError("Could not load the preview.");
    } finally {
      setPreviewLoading(false);
    }
  }

  async function handleCreate() {
    if (payload.pending_card_id == null) return;
    setCreating(true);
    setActionError(null);
    try {
      const res = await fetch(`/api/pending-cards/${payload.pending_card_id}/create`, {
        method: "POST",
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        const detail = body?.detail;
        const bugReportId =
          detail && typeof detail === "object" ? detail.bug_report_id : undefined;
        const message =
          detail && typeof detail === "object" && typeof detail.error === "string"
            ? detail.error
            : `Create failed (${res.status})`;
        throw new Error(
          bugReportId != null ? `${message} (bug report #${bugReportId} filed)` : message
        );
      }
      const data = (await res.json()) as { note_id: number };
      onUpdatePayload({ ...payload, status: "created", note_id: data.note_id });
      setPreviewOpen(false);
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : "Could not create the card in Anki."
      );
    } finally {
      setCreating(false);
    }
  }

  async function handleDiscard() {
    if (payload.pending_card_id == null) return;
    setDiscarding(true);
    setActionError(null);
    try {
      const res = await fetch(`/api/pending-cards/${payload.pending_card_id}/discard`, {
        method: "POST",
      });
      if (!res.ok) throw new Error(`Discard failed (${res.status})`);
      onUpdatePayload({ ...payload, status: "discarded" });
      setPreviewOpen(false);
    } catch {
      setActionError("Could not discard the draft.");
    } finally {
      setDiscarding(false);
    }
  }

  return (
    <div className="mt-2 rounded-xl border border-border bg-surface p-4">
      <div className="mb-3 flex items-center justify-between">
        <p className="text-sm font-medium text-foreground/70">
          {status === "created" ? "Card added to Anki" : "Card draft"}
        </p>
        {payload.note_id != null && (
          <span className="text-xs text-foreground/40">note #{payload.note_id}</span>
        )}
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
        <dt className="text-foreground/60">Deck</dt>
        <dd>{payload.deck_name ?? "—"}</dd>
        <dt className="text-foreground/60">Note type</dt>
        <dd>{payload.model_name ?? "—"}</dd>
        {Object.entries(fields).map(([name, value]) => (
          <Fragment key={name}>
            <dt className="text-foreground/60">{name}</dt>
            <dd className="whitespace-pre-wrap">{value}</dd>
          </Fragment>
        ))}
        {payload.tags && payload.tags.length > 0 && (
          <>
            <dt className="text-foreground/60">Tags</dt>
            <dd>{payload.tags.join(", ")}</dd>
          </>
        )}
      </dl>

      {status === "pending" && (
        <>
          {actionError && <p className="mt-3 text-xs text-red-500">{actionError}</p>}
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              disabled={disabled || previewLoading}
              onClick={openPreview}
              className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-1 text-xs font-medium hover:bg-foreground/5 disabled:opacity-50"
            >
              {previewLoading && <Loader2 size={12} className="animate-spin" />}
              Preview
            </button>
            <button
              type="button"
              disabled={disabled || creating || discarding}
              onClick={handleCreate}
              className="flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1 text-xs font-medium text-accent-foreground disabled:opacity-50"
            >
              {creating && <Loader2 size={12} className="animate-spin" />}
              Create
            </button>
            <button
              type="button"
              disabled={disabled || creating || discarding}
              onClick={handleDiscard}
              className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-1 text-xs font-medium text-red-500 hover:bg-red-500/10 disabled:opacity-50"
            >
              {discarding && <Loader2 size={12} className="animate-spin" />}
              Discard
            </button>
          </div>
          {previewError && <p className="mt-2 text-xs text-red-500">{previewError}</p>}

          {previewOpen && preview && (
            <PendingCardPreviewModal
              preview={preview}
              side={previewSide}
              onSideChange={setPreviewSide}
              width={previewWidth}
              onWidthChange={setPreviewWidth}
              onClose={() => setPreviewOpen(false)}
              onCreate={handleCreate}
              onDiscard={handleDiscard}
              creating={creating}
              discarding={discarding}
              actionError={actionError}
            />
          )}
        </>
      )}

      {status === "created" && (
        <button
          type="button"
          disabled={disabled}
          onClick={() =>
            onRequestChange(
              `Please update the note you just created (note #${payload.note_id ?? "?"}): `
            )
          }
          className="mt-3 rounded-lg border border-border px-3 py-1 text-xs font-medium hover:bg-foreground/5 disabled:opacity-50"
        >
          Request a change
        </button>
      )}

      {status === "discarded" && (
        <p className="mt-3 text-xs text-foreground/50">Draft discarded.</p>
      )}
    </div>
  );
}
