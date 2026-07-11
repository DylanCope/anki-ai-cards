"use client";

import type { ModelInfo } from "@/app/lib/types";

interface Props {
  models: ModelInfo[];
  selectedId: string;
  onSelect: (modelId: string) => void;
  disabled: boolean;
}

function formatPrice(model: ModelInfo): string {
  return `$${model.input_price_per_mtok.toFixed(2)} / $${model.output_price_per_mtok.toFixed(2)} per MTok`;
}

export default function ModelSelector({ models, selectedId, onSelect, disabled }: Props) {
  const selected = models.find((m) => m.id === selectedId);

  return (
    <div className="flex flex-col gap-1">
      <select
        value={selectedId}
        onChange={(event) => onSelect(event.target.value)}
        disabled={disabled || models.length === 0}
        className="rounded-lg border border-border bg-transparent px-3 py-1 text-xs disabled:opacity-50"
      >
        <optgroup label="Claude (Anthropic)">
          {models
            .filter((m) => m.provider === "anthropic")
            .map((m) => (
              <option key={m.id} value={m.id}>
                {m.display_name} — {formatPrice(m)}
              </option>
            ))}
        </optgroup>
        <optgroup label="Gemini (Google)">
          {models
            .filter((m) => m.provider === "gemini")
            .map((m) => (
              <option key={m.id} value={m.id}>
                {m.display_name} — {formatPrice(m)}
              </option>
            ))}
        </optgroup>
      </select>
      {selected && (
        <p className="max-w-xs text-[11px] text-foreground/50">
          {selected.description}
        </p>
      )}
    </div>
  );
}
