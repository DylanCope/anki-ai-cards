export default function SignIn() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4">
      <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-accent font-jp text-2xl font-bold text-accent-foreground">
        暗助
      </div>
      <h1 className="text-xl font-bold">Anjo</h1>
      <p className="max-w-sm text-center text-sm text-foreground/60">
        Sign in with the Google account.
      </p>
      <a
        href="/auth/google/login"
        className="rounded-full bg-accent px-5 py-2 text-sm font-medium text-accent-foreground"
      >
        Sign in with Google
      </a>
    </div>
  );
}
