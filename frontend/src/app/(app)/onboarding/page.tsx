"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiJson, ApiError } from "@/lib/api";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";
import type { Child, ChildCreateRequest, FeedingType } from "@/lib/types";

const FEEDING_OPTIONS: { value: FeedingType; label: string }[] = [
  { value: "breast", label: "Breast" },
  { value: "formula", label: "Formula" },
  { value: "mixed", label: "Both" },
  { value: "solids", label: "Solids too" },
];

export default function OnboardingPage() {
  const router = useRouter();

  const [name, setName] = useState("");
  const [birthDate, setBirthDate] = useState("");
  const [bornEarly, setBornEarly] = useState(false);
  const [dueDate, setDueDate] = useState("");
  const [feeding, setFeeding] = useState<FeedingType | null>(null);
  const [notes, setNotes] = useState("");
  const [pediatricianPhone, setPediatricianPhone] = useState("");

  const [step, setStep] = useState<"profile" | "consent">("profile");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function saveChild(event: React.FormEvent) {
    event.preventDefault();
    if (!birthDate) return;
    setSaving(true);
    setError(null);

    const payload: ChildCreateRequest = {
      name: name.trim() || "Baby",
      birth_date: birthDate,
      due_date: bornEarly && dueDate ? dueDate : null,
      feeding_type: feeding,
      notes: notes.trim() || null,
      pediatrician_phone: pediatricianPhone.trim() || null,
    };

    try {
      await apiJson<Child>("/api/v1/children", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setStep("consent");
    } catch (e) {
      setError(
        e instanceof ApiError ? e.message : "Could not save. Please try again.",
      );
    } finally {
      setSaving(false);
    }
  }

  async function acceptAndContinue() {
    setSaving(true);
    setError(null);
    try {
      const supabase = getSupabaseBrowserClient();
      if (supabase) {
        const {
          data: { user },
        } = await supabase.auth.getUser();
        if (user) {
          await supabase
            .from("profiles")
            .update({ disclaimer_accepted_at: new Date().toISOString() })
            .eq("id", user.id);
        }
      }
      router.push("/chat");
    } catch {
      setError("Something went wrong. Please try again.");
      setSaving(false);
    }
  }

  if (step === "consent") {
    return (
      <main className="safe-top safe-bottom mx-auto flex w-full max-w-md flex-1 flex-col justify-center px-6 py-10">
        <div className="rounded-2xl bg-surface p-6">
          <h1 className="text-xl font-semibold">One thing before we start</h1>
          <p className="mt-4 leading-relaxed text-muted">
            I’m a companion, not a doctor. I can help you think through the
            night, but I don’t diagnose or replace medical care.
          </p>
          <p className="mt-3 leading-relaxed text-muted">
            If your baby ever seems to be in danger, call{" "}
            <a href="tel:911" className="font-semibold text-foreground underline">
              911
            </a>{" "}
            or your pediatrician first.
          </p>
          <button
            type="button"
            onClick={acceptAndContinue}
            disabled={saving}
            className="mt-6 min-h-14 w-full rounded-xl bg-accent text-lg font-semibold text-background disabled:opacity-60"
          >
            I understand — let’s go
          </button>
          {error && (
            <p className="mt-3 text-danger" role="alert">
              {error}
            </p>
          )}
        </div>
      </main>
    );
  }

  return (
    <main className="safe-top safe-bottom mx-auto flex w-full max-w-md flex-1 flex-col px-6 py-8">
      <h1 className="text-2xl font-semibold">Tell me about your baby</h1>
      <p className="mt-1 text-muted">
        So I never ask you to repeat the basics at 3am.
      </p>

      <form onSubmit={saveChild} className="mt-6 flex flex-col gap-5">
        <div>
          <label htmlFor="name" className="mb-1 block text-sm text-muted">
            Name (optional)
          </label>
          <input
            id="name"
            type="text"
            placeholder="Baby"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="min-h-14 w-full rounded-xl border border-border-soft bg-surface px-4 placeholder:text-muted focus:border-accent focus:outline-none"
          />
        </div>

        <div>
          <label htmlFor="birth_date" className="mb-1 block text-sm text-muted">
            Birth date
          </label>
          <input
            id="birth_date"
            type="date"
            required
            value={birthDate}
            max={new Date().toISOString().slice(0, 10)}
            onChange={(e) => setBirthDate(e.target.value)}
            className="min-h-14 w-full rounded-xl border border-border-soft bg-surface px-4 text-lg focus:border-accent focus:outline-none"
          />
        </div>

        <button
          type="button"
          role="switch"
          aria-checked={bornEarly}
          onClick={() => setBornEarly((v) => !v)}
          className={`flex min-h-14 items-center justify-between rounded-xl border px-4 text-left ${
            bornEarly
              ? "border-accent bg-accent-soft"
              : "border-border-soft bg-surface"
          }`}
        >
          <span>Born 3+ weeks early?</span>
          <span
            aria-hidden
            className={`inline-block h-7 w-12 rounded-full p-1 transition-colors ${
              bornEarly ? "bg-accent" : "bg-border-soft"
            }`}
          >
            <span
              className={`block h-5 w-5 rounded-full bg-background transition-transform ${
                bornEarly ? "translate-x-5" : ""
              }`}
            />
          </span>
        </button>

        {bornEarly && (
          <div>
            <label htmlFor="due_date" className="mb-1 block text-sm text-muted">
              Original due date
            </label>
            <input
              id="due_date"
              type="date"
              value={dueDate}
              onChange={(e) => setDueDate(e.target.value)}
              className="min-h-14 w-full rounded-xl border border-border-soft bg-surface px-4 text-lg focus:border-accent focus:outline-none"
            />
            <p className="mt-1 text-sm text-muted">
              We’ll use adjusted age where it matters.
            </p>
          </div>
        )}

        <div>
          <span className="mb-1 block text-sm text-muted">Feeding</span>
          <div className="grid grid-cols-2 gap-2">
            {FEEDING_OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                aria-pressed={feeding === option.value}
                onClick={() =>
                  setFeeding((current) =>
                    current === option.value ? null : option.value,
                  )
                }
                className={`min-h-14 rounded-xl border px-3 font-medium ${
                  feeding === option.value
                    ? "border-accent bg-accent-soft text-foreground"
                    : "border-border-soft bg-surface text-muted"
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label htmlFor="notes" className="mb-1 block text-sm text-muted">
            Anything else I should know? (optional)
          </label>
          <textarea
            id="notes"
            rows={2}
            placeholder="Reflux, allergies, anything on your mind…"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className="w-full rounded-xl border border-border-soft bg-surface px-4 py-3 placeholder:text-muted focus:border-accent focus:outline-none"
          />
        </div>

        <div>
          <label htmlFor="ped_phone" className="mb-1 block text-sm text-muted">
            Pediatrician phone (optional)
          </label>
          <input
            id="ped_phone"
            type="tel"
            inputMode="tel"
            placeholder="(555) 555-5555"
            value={pediatricianPhone}
            onChange={(e) => setPediatricianPhone(e.target.value)}
            className="min-h-14 w-full rounded-xl border border-border-soft bg-surface px-4 placeholder:text-muted focus:border-accent focus:outline-none"
          />
          <p className="mt-1 text-sm text-muted">
            We’ll surface this if you ever need it fast.
          </p>
        </div>

        <button
          type="submit"
          disabled={saving || !birthDate}
          className="min-h-14 rounded-xl bg-accent text-lg font-semibold text-background disabled:opacity-60"
        >
          {saving ? "Saving…" : "Continue"}
        </button>

        {error && (
          <p className="text-danger" role="alert">
            {error}
          </p>
        )}
      </form>
    </main>
  );
}
