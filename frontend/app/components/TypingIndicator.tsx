export default function TypingIndicator() {
  return (
    <div className="flex justify-start">
      <div className="flex items-center gap-1 rounded-xl border border-border bg-surface px-4 py-3">
        <span className="h-2 w-2 animate-bounce rounded-full bg-foreground/40 [animation-delay:-0.3s]" />
        <span className="h-2 w-2 animate-bounce rounded-full bg-foreground/40 [animation-delay:-0.15s]" />
        <span className="h-2 w-2 animate-bounce rounded-full bg-foreground/40" />
      </div>
    </div>
  );
}
