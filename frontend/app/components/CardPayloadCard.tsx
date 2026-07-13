"use client";

import { Fragment } from "react";
import type { CardPayload } from "@/app/lib/types";

interface Props {
  payload: CardPayload;
  onRequestChange: (message: string) => void;
  disabled: boolean;
}

export default function CardPayloadCard({ payload, onRequestChange, disabled }: Props) {
  const fields = payload.fields ?? {};

  return (
    <div className="mt-2 rounded-xl border border-border bg-surface p-4">
      <div className="mb-3 flex items-center justify-between">
        <p className="text-sm font-medium text-foreground/70">Card added to Anki</p>
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
    </div>
  );
}
