"use client";

import { useEffect, useState } from "react";
import { Sparkles, X } from "lucide-react";
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

const PROVIDER_LABELS: Record<ModelInfo["provider"], string> = {
  anthropic: "Claude (Anthropic)",
  gemini: "Gemini (Google)",
};

export default function AiSettingsButton({ models, selectedId, onSelect, disabled }: Props) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open]);

  const providers = Array.from(new Set(models.map((m) => m.provider)));

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        disabled={disabled || models.length === 0}
        aria-label="AI settings"
        title="AI settings"
        className="flex h-9 w-9 items-center justify-center rounded-lg border border-border text-foreground/70 transition-colors hover:bg-foreground/5 disabled:opacity-50"
      >
        <Sparkles size={18} />
      </button>

      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
          onClick={() => setOpen(false)}
        >
          <div
            className="flex max-h-[80vh] w-full max-w-md flex-col rounded-xl border border-border bg-surface shadow-xl"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-border px-5 py-4">
              <div className="flex items-center gap-2">
                <Sparkles size={16} className="text-accent" />
                <h2 className="text-sm font-semibold text-foreground">AI Settings</h2>
              </div>
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-label="Close"
                className="rounded-lg p-1 text-foreground/50 hover:bg-foreground/5 hover:text-foreground"
              >
                <X size={16} />
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-3">
              {providers.map((provider) => (
                <div key={provider} className="mb-3 last:mb-0">
                  <p className="px-2 py-1 text-xs font-semibold uppercase tracking-wide text-foreground/40">
                    {PROVIDER_LABELS[provider] ?? provider}
                  </p>
                  <div className="flex flex-col gap-1.5">
                    {models
                      .filter((m) => m.provider === provider)
                      .map((model) => {
                        const isSelected = model.id === selectedId;
                        return (
                          <button
                            key={model.id}
                            type="button"
                            onClick={() => onSelect(model.id)}
                            className={`rounded-lg border px-3 py-2 text-left transition-colors ${
                              isSelected
                                ? "border-accent bg-accent/10"
                                : "border-border hover:bg-foreground/5"
                            }`}
                          >
                            <p className="text-sm font-medium text-foreground">
                              {model.display_name}
                            </p>
                            <p className="mt-0.5 text-xs text-foreground/50">
                              {formatPrice(model)}
                            </p>
                            <p className="mt-1 text-xs text-foreground/60">{model.description}</p>
                          </button>
                        );
                      })}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
