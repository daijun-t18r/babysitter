"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch, apiJson, ApiError, getApiBaseUrl } from "@/lib/api";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";
import type { MeResponse } from "@/lib/types";

type LoadState = "loading" | "ready" | "unconfigured" | "error";

const CONFIRM_WORD = "DELETE";

export default function SettingsPage() {
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [email, setEmail] = useState<string | null>(null);
  const [confirmText, setConfirmText] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      if (!getApiBaseUrl()) {
        setLoadState("unconfigured");
        return;
      }
      try {
        const me = await apiJson<MeResponse>("/api/v1/me");
        if (cancelled) return;
        setEmail(me.email);
        setLoadState("ready");
      } catch (e) {
        if (cancelled) return;
        setLoadState(
          e instanceof ApiError && e.code === "not_configured"
            ? "unconfigured"
            : "error",
        );
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  async function deleteAccount() {
    if (confirmText !== CONFIRM_WORD || deleting) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      const response = await apiFetch("/api/v1/me", { method: "DELETE" });
      if (!response.ok) {
        throw new ApiError(`Request failed (${response.status})`, response.status);
      }
      await getSupabaseBrowserClient()?.auth.signOut();
      // Full reload clears every bit of client state on the way out.
      window.location.assign("/login?farewell=1");
    } catch {
      setDeleting(false);
      setDeleteError(
        "Couldn’t delete your account right now. Nothing was changed — please try again.",
      );
    }
  }

  return (
    <main className="safe-top safe-bottom mx-auto flex w-full max-w-md flex-1 flex-col px-4 py-4">
      <div className="flex items-center gap-3">
        <Link
          href="/history"
          aria-label="Back to past nights"
          className="flex h-12 w-12 items-center justify-center rounded-full bg-surface text-muted"
        >
          <svg
            width="22"
            height="22"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden
          >
            <path d="M15 5l-7 7 7 7" />
          </svg>
        </Link>
        <h1 className="text-xl font-semibold">Settings</h1>
      </div>

      {loadState === "loading" && (
        <p className="mt-10 text-center text-muted">One moment…</p>
      )}
      {loadState === "unconfigured" && (
        <p className="mt-10 text-center text-muted">
          Settings aren’t available in this environment.
        </p>
      )}
      {loadState === "error" && (
        <p className="mt-10 text-center text-muted">
          Couldn’t load your account right now.
        </p>
      )}

      {loadState === "ready" && (
        <>
          <section className="mt-6 rounded-2xl bg-surface p-5">
            <h2 className="text-sm font-medium uppercase tracking-wide text-muted">
              Account
            </h2>
            <p className="mt-2 break-all font-medium">
              {email ?? "Signed in"}
            </p>
          </section>

          <section className="mt-6 rounded-2xl border border-danger-deep p-5">
            <h2 className="text-sm font-medium uppercase tracking-wide text-danger">
              Danger zone
            </h2>
            <p className="mt-2 leading-relaxed text-muted">
              Deleting your account permanently removes everything — your
              children’s profiles, conversations, and timeline. There is no
              undo.
            </p>
            <label htmlFor="delete-confirm" className="mt-4 block text-sm text-muted">
              Type {CONFIRM_WORD} to confirm
            </label>
            <input
              id="delete-confirm"
              type="text"
              autoComplete="off"
              autoCapitalize="characters"
              spellCheck={false}
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              className="mt-2 min-h-12 w-full rounded-xl border border-border-soft bg-surface px-4 text-foreground placeholder:text-muted focus:border-danger focus:outline-none"
              placeholder={CONFIRM_WORD}
            />
            <button
              type="button"
              onClick={deleteAccount}
              disabled={confirmText !== CONFIRM_WORD || deleting}
              className="mt-4 min-h-14 w-full rounded-xl bg-danger px-4 text-lg font-semibold text-background disabled:opacity-40"
            >
              {deleting ? "Deleting…" : "Delete my account"}
            </button>
            {deleteError && (
              <p className="mt-3 text-sm text-danger" role="alert">
                {deleteError}
              </p>
            )}
          </section>
        </>
      )}
    </main>
  );
}
