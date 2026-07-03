"use client";

import type { AudioOptionsPayload } from "@/app/lib/types";

interface Props {
  payload: AudioOptionsPayload;
  onPick: (message: string) => void;
  disabled: boolean;
}

export default function AudioOptionsCard({ payload, onPick, disabled }: Props) {
  return (
    <div className="mt-2 rounded-lg border border-zinc-200 bg-zinc-50 p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <p className="mb-3 text-sm font-medium text-zinc-700 dark:text-zinc-300">
        Audio options{payload.text ? ` for "${payload.text}"` : ""}
      </p>
      <div className="flex flex-col gap-3">
        {payload.options.map((base64, index) => (
          <div key={index} className="flex items-center gap-3">
            <span className="w-16 shrink-0 text-sm text-zinc-500 dark:text-zinc-400">
              Option {index + 1}
            </span>
            <audio controls className="h-8 flex-1" src={`data:audio/mpeg;base64,${base64}`} />
            <button
              type="button"
              disabled={disabled}
              onClick={() => onPick(`Use audio option ${index + 1}.`)}
              className="shrink-0 rounded-full bg-foreground px-3 py-1 text-xs font-medium text-background disabled:opacity-50"
            >
              Pick
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
