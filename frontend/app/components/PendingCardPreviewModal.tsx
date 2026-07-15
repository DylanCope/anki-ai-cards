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
// still wins. Unlike the earlier version of this fallback, it's applied in
// BOTH themes (not just dark) and uses this app's own `--background`/
// `--foreground` palette (globals.css) rather than a guessed hex, so a card
// with no background of its own always blends into the surrounding panel
// instead of standing out as browser-default white.
const THEME_FALLBACK = {
  light: { background: "#fafafa", foreground: "#18181b" },
  dark: { background: "#030712", foreground: "#f4f4f5" },
};

function buildSrcDoc(preview: PendingCardPreview, side: PreviewSide, nightMode: boolean): string {
  const html = side === "front" ? preview.front_html : preview.back_html;
  const nightClasses = nightMode ? " nightMode night_mode" : "";
  const { background, foreground } = nightMode ? THEME_FALLBACK.dark : THEME_FALLBACK.light;
  return `<!DOCTYPE html><html class="${nightMode ? "nightMode night_mode" : ""}"><head><style>
body { font-family: Arial, Helvetica, "Noto Sans JP", sans-serif; margin: 0; height: 100%; }
html { height: 100%; }
html, body { background: ${background}; color: ${foreground}; }
audio { display: block; max-width: 100%; height: 32px; margin: 4px 0; }
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
              // allow-scripts only (no allow-same-origin) — srcDoc iframes
              // with just allow-scripts get a unique opaque origin, so any
              // JS a note type's template embeds (e.g. Migaku's
              // furigana/pitch-accent rendering) can run without being able
              // to read this app's cookies/session or call its API.
              sandbox="allow-scripts"
              srcDoc={buildSrcDoc(preview, side, theme === "dark")}
              className="h-full w-full rounded-md border border-border"
              title="Card preview"
            />
          </div>
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
