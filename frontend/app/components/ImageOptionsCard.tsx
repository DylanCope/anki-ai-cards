"use client";

import type { ImageOptionsPayload } from "@/app/lib/types";

interface Props {
  payload: ImageOptionsPayload;
  onPick: (message: string) => void;
  disabled: boolean;
}

export default function ImageOptionsCard({ payload, onPick, disabled }: Props) {
  return (
    <div className="mt-2 rounded-xl border border-border bg-surface p-4">
      <p className="mb-3 text-sm font-medium text-foreground/70">
        Image options{payload.query_or_prompt ? ` for "${payload.query_or_prompt}"` : ""}
      </p>
      <div className="flex flex-wrap gap-4">
        {payload.options.map((base64, index) => (
          <div key={index} className="flex flex-col items-center gap-2">
            {/* eslint-disable-next-line @next/next/no-img-element -- variable-format base64 data URI, not a fit for next/image */}
            <img
              src={`data:${payload.content_types[index] ?? "image/jpeg"};base64,${base64}`}
              alt={`Option ${index + 1}`}
              className="h-32 w-32 rounded-lg object-cover"
            />
            <button
              type="button"
              disabled={disabled}
              onClick={() =>
                onPick(
                  `Use image option ${index + 1} (image_id ${payload.image_ids[index]}).`
                )
              }
              className="rounded-full bg-accent px-3 py-1 text-xs font-medium text-accent-foreground disabled:opacity-50"
            >
              Pick
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
