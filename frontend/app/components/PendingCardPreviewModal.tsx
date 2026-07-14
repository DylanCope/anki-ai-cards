"use client";

import { useEffect } from "react";
import { Loader2, Monitor, Smartphone, X } from "lucide-react";
import type { PendingCardPreview } from "@/app/lib/types";
import { useTheme } from "@/app/components/ThemeProvider";

type PreviewSide = "front" | "back";
type PreviewWidth = "mobile" | "pc";

interface Props {
  preview: PendingCardPreview;
  side: PreviewSide;
  onSideChange: (side: PreviewSide) => void;
  width: PreviewWidth;
  onWidthChange: (width: PreviewWidth) => void;
  onClose: () => void;
  onCreate: () => void;
  onDiscard: () => void;
  creating: boolean;
  discarding: boolean;
  actionError: string | null;
}

// Real Anki toggles a `nightMode` class (confirmed against Dylan's actual
// Cloze+ styling, which has `.nightMode .cloze { color: lightblue; }`) on an
// ancestor of `.card` when night mode is active. Also add the less common
// `night_mode` snake_case variant some other shared note types use — added
// to both the root element and the `.card` div itself so ancestor selectors
// (`.nightMode .foo`) and compound selectors (`.card.nightMode`) both match.
//
// Real Anki's reviewer also ships its own base dark background/text-color
// for night mode, which the note's own CSS cascades on top of and can
// override — e.g. Dylan's "Cloze" note type hardcodes `.card { background:
// white }` with no night-mode override, so it stays white under real Anki's
// night mode too; "Cloze+" leaves its background undefined (a commented-out
// CSS variable block), so Anki's own dark default shows through. The
// low-specificity `body`/`html` rule below approximates that same base
// layer, loaded before the note's own CSS so anything more specific in it
// still wins.
function buildSrcDoc(preview: PendingCardPreview, side: PreviewSide, nightMode: boolean): string {
  const html = side === "front" ? preview.front_html : preview.back_html;
  const nightClasses = nightMode ? " nightMode night_mode" : "";
  const nightBase = nightMode
    ? "html, body { background: #2f2f31; color: #fff; }"
    : "";
  return `<!DOCTYPE html><html class="${nightMode ? "nightMode night_mode" : ""}"><head><style>
body { font-family: Arial, Helvetica, "Noto Sans JP", sans-serif; margin: 0; height: 100%; }
html { height: 100%; }
${nightBase}
${preview.css}
</style></head><body><div class="card${nightClasses}">${html}</div></body></html>`;
}

export default function PendingCardPreviewModal({
  preview,
  side,
  onSideChange,
  width,
  onWidthChange,
  onClose,
  onCreate,
  onDiscard,
  creating,
  discarding,
  actionError,
}: Props) {
  const { theme } = useTheme();

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-md"
      onClick={onClose}
    >
      <div
        className="relative flex h-[90vh] w-[92vw] flex-col overflow-hidden rounded-xl border border-border bg-surface shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex shrink-0 items-center justify-between gap-2 border-b border-border p-3">
          <div className="flex gap-1 rounded-lg border border-border p-0.5">
            <button
              type="button"
              onClick={() => onSideChange("front")}
              className={`rounded-md px-3 py-1 text-xs font-medium ${
                side === "front"
                  ? "bg-accent text-accent-foreground"
                  : "text-foreground/60 hover:bg-foreground/5"
              }`}
            >
              Front
            </button>
            <button
              type="button"
              onClick={() => onSideChange("back")}
              className={`rounded-md px-3 py-1 text-xs font-medium ${
                side === "back"
                  ? "bg-accent text-accent-foreground"
                  : "text-foreground/60 hover:bg-foreground/5"
              }`}
            >
              Back
            </button>
          </div>
          <div className="flex items-center gap-2">
            <div className="flex gap-1 rounded-lg border border-border p-0.5">
              <button
                type="button"
                aria-label="Mobile width"
                title="Mobile width"
                onClick={() => onWidthChange("mobile")}
                className={`rounded-md p-1.5 ${
                  width === "mobile"
                    ? "bg-accent text-accent-foreground"
                    : "text-foreground/60 hover:bg-foreground/5"
                }`}
              >
                <Smartphone size={14} />
              </button>
              <button
                type="button"
                aria-label="PC width"
                title="PC width"
                onClick={() => onWidthChange("pc")}
                className={`rounded-md p-1.5 ${
                  width === "pc"
                    ? "bg-accent text-accent-foreground"
                    : "text-foreground/60 hover:bg-foreground/5"
                }`}
              >
                <Monitor size={14} />
              </button>
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="rounded-full border border-border p-1.5 text-foreground/70 hover:text-foreground"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        <div className="flex min-h-0 flex-1 flex-col items-center gap-3 overflow-y-auto p-4">
          <div
            className={`min-h-[55vh] w-full flex-1 ${
              width === "mobile" ? "max-w-[420px]" : "max-w-[900px]"
            }`}
          >
            <iframe
              sandbox=""
              srcDoc={buildSrcDoc(preview, side, theme === "dark")}
              className="h-full w-full rounded-md border border-border"
              title="Card preview"
            />
          </div>
          {preview.audio_base64 && (
            <div className="flex w-full max-w-[900px] shrink-0 items-center gap-2">
              <span className="text-xs text-foreground/60">Attached audio</span>
              <audio
                controls
                className="h-8 flex-1"
                src={`data:audio/mpeg;base64,${preview.audio_base64}`}
              />
            </div>
          )}
          {preview.picture_base64 && (
            <div className="flex w-full max-w-[900px] shrink-0 flex-col items-start gap-1">
              <span className="text-xs text-foreground/60">Attached image</span>
              {/* eslint-disable-next-line @next/next/no-img-element -- variable-format base64 data URI, not a fit for next/image */}
              <img
                src={`data:${preview.picture_content_type ?? "image/jpeg"};base64,${preview.picture_base64}`}
                alt="Attached"
                className="max-h-40 rounded-md border border-border object-contain"
              />
            </div>
          )}
        </div>

        <div className="flex shrink-0 items-center justify-end gap-2 border-t border-border p-3">
          {actionError && <p className="mr-auto text-xs text-red-500">{actionError}</p>}
          <button
            type="button"
            disabled={creating || discarding}
            onClick={onDiscard}
            className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-red-500 hover:bg-red-500/10 disabled:opacity-50"
          >
            {discarding && <Loader2 size={12} className="animate-spin" />}
            Discard
          </button>
          <button
            type="button"
            disabled={creating || discarding}
            onClick={onCreate}
            className="flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-accent-foreground disabled:opacity-50"
          >
            {creating && <Loader2 size={12} className="animate-spin" />}
            Create
          </button>
        </div>
      </div>
    </div>
  );
}
