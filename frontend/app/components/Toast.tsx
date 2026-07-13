export default function Toast({
  message,
  onDismiss,
}: {
  message: string;
  onDismiss: () => void;
}) {
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-4 z-50 flex justify-center px-4">
      <div className="pointer-events-auto flex max-w-md items-start gap-3 rounded-xl border border-red-500/30 bg-surface px-4 py-3 text-sm text-foreground shadow-lg">
        <p className="flex-1">{message}</p>
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss"
          className="text-foreground/50 hover:text-foreground"
        >
          ✕
        </button>
      </div>
    </div>
  );
}
