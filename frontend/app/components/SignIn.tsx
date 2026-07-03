export default function SignIn() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4">
      <h1 className="text-xl font-semibold">anki-ai-cards</h1>
      <p className="max-w-sm text-center text-sm text-zinc-500 dark:text-zinc-400">
        Sign in with the Google account that has access to your lesson doc and
        Anki collection.
      </p>
      <a
        href="/auth/google/login"
        className="rounded-full bg-foreground px-5 py-2 text-sm font-medium text-background"
      >
        Sign in with Google
      </a>
    </div>
  );
}
