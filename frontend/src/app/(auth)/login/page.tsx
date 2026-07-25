"use client";

import { useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";

type Status = "idle" | "sending" | "sent" | "error";

/** The URL query never changes without a navigation — nothing to subscribe to. */
function subscribeNoop(): () => void {
  return () => {};
}

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  // Shown after account deletion (?farewell=1). Read from window instead of
  // useSearchParams to keep this page statically prerenderable; the server
  // snapshot is false so hydration stays consistent.
  const farewell = useSyncExternalStore(
    subscribeNoop,
    () => new URLSearchParams(window.location.search).has("farewell"),
    () => false,
  );

  const supabase = getSupabaseBrowserClient();

  async function sendMagicLink(event: React.FormEvent) {
    event.preventDefault();
    if (!supabase || !email.trim()) return;
    setStatus("sending");
    setErrorMessage(null);
    const { error } = await supabase.auth.signInWithOtp({
      email: email.trim(),
      options: {
        emailRedirectTo: `${window.location.origin}/auth/callback`,
      },
    });
    if (error) {
      setStatus("error");
      setErrorMessage(error.message);
    } else {
      setStatus("sent");
    }
  }

  async function signInWithGoogle() {
    if (!supabase) return;
    setErrorMessage(null);
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: `${window.location.origin}/auth/callback`,
      },
    });
    if (error) setErrorMessage(error.message);
  }

  return (
    <main className="safe-top safe-bottom mx-auto flex w-full max-w-md flex-1 flex-col justify-center px-6 py-10">
      <div className="mb-10 text-center">
        <div className="mb-3 text-4xl" aria-hidden>
          ☾
        </div>
        <h1 className="text-2xl font-semibold">Midnight Companion</h1>
        <p className="mt-2 text-muted">
          A calm voice for the hardest hours.
        </p>
      </div>

      {farewell && (
        <p className="mb-6 rounded-2xl bg-surface p-5 text-center leading-relaxed text-muted">
          Your account and everything in it has been deleted. Thank you for
          letting us keep you company — you’re always welcome back.
        </p>
      )}

      {!supabase ? (
        <p className="rounded-2xl bg-surface p-5 text-center text-muted">
          Sign-in is not configured in this environment.
        </p>
      ) : status === "sent" ? (
        <div className="rounded-2xl bg-surface p-6 text-center">
          <p className="text-lg font-medium">Check your email</p>
          <p className="mt-2 text-muted">
            We sent a sign-in link to {email}. Tap it on this device.
          </p>
          <button
            type="button"
            onClick={() => setStatus("idle")}
            className="mt-5 min-h-12 w-full rounded-xl border border-border-soft px-4 text-muted"
          >
            Use a different email
          </button>
        </div>
      ) : (
        <>
          <form onSubmit={sendMagicLink} className="flex flex-col gap-3">
            <label htmlFor="email" className="sr-only">
              Email address
            </label>
            <input
              id="email"
              type="email"
              inputMode="email"
              autoComplete="email"
              required
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="min-h-14 rounded-xl border border-border-soft bg-surface px-4 text-foreground placeholder:text-muted focus:border-accent focus:outline-none"
            />
            <button
              type="submit"
              disabled={status === "sending"}
              className="min-h-14 rounded-xl bg-accent px-4 text-lg font-semibold text-background disabled:opacity-60"
            >
              {status === "sending" ? "Sending link…" : "Email me a sign-in link"}
            </button>
          </form>

          <div className="my-5 flex items-center gap-3 text-muted">
            <div className="h-px flex-1 bg-border-soft" />
            <span className="text-sm">or</span>
            <div className="h-px flex-1 bg-border-soft" />
          </div>

          <button
            type="button"
            onClick={signInWithGoogle}
            className="min-h-14 rounded-xl border border-border-soft bg-surface px-4 text-lg font-medium"
          >
            Continue with Google
          </button>
        </>
      )}

      {errorMessage && (
        <p className="mt-4 text-center text-danger" role="alert">
          {errorMessage}
        </p>
      )}

      <p className="mt-10 text-center text-sm text-muted">
        Not medical advice. In an emergency call{" "}
        <a href="tel:911" className="font-semibold text-foreground underline">
          911
        </a>
        .
      </p>

      <p className="mt-4 text-center">
        <Link
          href="/sos"
          className="inline-flex min-h-12 items-center justify-center px-4 text-muted underline"
        >
          I just need a break right now
        </Link>
      </p>
    </main>
  );
}
