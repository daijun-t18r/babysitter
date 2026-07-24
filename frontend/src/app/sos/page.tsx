"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  MATERNAL_MENTAL_HEALTH,
  SUICIDE_CRISIS_LIFELINE,
} from "@/lib/emergency";

const BREATHING_SECONDS = 90;

type Phase = "script" | "breathing" | "after";

// 4-7-8 pacing, mirrored by the CSS animation (19s cycle).
function breathLabel(elapsed: number): string {
  const inCycle = elapsed % 19;
  if (inCycle < 4) return "Breathe in";
  if (inCycle < 11) return "Hold";
  return "Breathe out slowly";
}

export default function SosPage() {
  const [phase, setPhase] = useState<Phase>("script");
  const [elapsed, setElapsed] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (phase !== "breathing") return;
    intervalRef.current = setInterval(() => {
      setElapsed((s) => {
        if (s + 1 >= BREATHING_SECONDS) {
          setPhase("after");
          return s + 1;
        }
        return s + 1;
      });
    }, 1000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [phase]);

  if (phase === "breathing") {
    const remaining = Math.max(0, BREATHING_SECONDS - elapsed);
    return (
      <main className="safe-top safe-bottom flex h-dvh flex-col items-center justify-center px-6">
        <div className="flex flex-1 flex-col items-center justify-center">
          <div
            aria-hidden
            className="breathing-circle h-56 w-56 rounded-full bg-accent-soft"
            style={{ boxShadow: "0 0 80px 20px rgba(217,158,90,0.15)" }}
          />
          <p className="mt-10 text-2xl font-medium" aria-live="polite">
            {breathLabel(elapsed)}
          </p>
          <p className="mt-2 text-muted">{remaining}s</p>
        </div>
        <button
          type="button"
          onClick={() => setPhase("after")}
          className="mb-4 flex min-h-12 items-center justify-center px-6 text-muted underline"
        >
          Skip
        </button>
      </main>
    );
  }

  if (phase === "after") {
    return (
      <main className="safe-top safe-bottom mx-auto flex h-dvh w-full max-w-md flex-col justify-center px-6">
        <h1 className="text-2xl font-semibold">Well done.</h1>
        <p className="mt-3 leading-relaxed text-muted">
          You just did something genuinely hard. Your baby is safe, and you
          gave yourself a moment — that’s good parenting, not giving up.
        </p>
        <p className="mt-3 leading-relaxed text-muted">
          When you’re ready, go back in. Or take another round of breaths —
          there’s no clock on this.
        </p>
        <div className="mt-8 flex flex-col gap-3">
          <Link
            href="/chat"
            className="flex min-h-14 items-center justify-center rounded-xl bg-accent text-lg font-semibold text-background"
          >
            Back to chat
          </Link>
          <button
            type="button"
            onClick={() => {
              setElapsed(0);
              setPhase("breathing");
            }}
            className="flex min-h-14 items-center justify-center rounded-xl border border-border-soft text-lg text-muted"
          >
            Breathe again
          </button>
        </div>
        <p className="mt-8 text-center text-sm leading-relaxed text-muted">
          Feeling like you might hurt yourself or your baby? Call or text{" "}
          <a href={SUICIDE_CRISIS_LIFELINE.tel} className="font-semibold text-foreground underline">
            988
          </a>{" "}
          or the Maternal Mental Health Hotline{" "}
          <a href={MATERNAL_MENTAL_HEALTH.tel} className="font-semibold text-foreground underline">
            {MATERNAL_MENTAL_HEALTH.display}
          </a>
          . Someone is awake with you.
        </p>
      </main>
    );
  }

  return (
    <main className="safe-top safe-bottom mx-auto flex h-dvh w-full max-w-md flex-col justify-center px-6">
      <h1 className="text-2xl font-semibold leading-snug">
        This is one of the hardest moments of parenting. Let’s take care of you
        for two minutes.
      </h1>
      <p className="mt-5 leading-relaxed text-muted">
        It is 100% safe to put your baby on their back in the crib — nothing
        else in it — and step into another room. Crying in a safe crib never
        hurt a baby.
      </p>
      <p className="mt-3 leading-relaxed text-muted">
        Set them down gently. Close the door if you need to. You’re not leaving
        them — you’re getting strong enough to come back.
      </p>
      <button
        type="button"
        onClick={() => {
          setElapsed(0);
          setPhase("breathing");
        }}
        className="mt-8 min-h-16 rounded-2xl bg-accent px-4 text-lg font-semibold text-background"
      >
        Baby is down — I’m in the other room
      </button>
      <Link
        href="/chat"
        className="mt-4 flex min-h-12 items-center justify-center text-muted underline"
      >
        Back to chat
      </Link>
    </main>
  );
}
