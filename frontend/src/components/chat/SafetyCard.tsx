"use client";

import { useState } from "react";
import {
  CRISIS_TEXT_LINE,
  MATERNAL_MENTAL_HEALTH,
  SUICIDE_CRISIS_LIFELINE,
  smsHref,
} from "@/lib/emergency";
import { CALL_911_REASONS } from "@/lib/types";

const REASON_LABELS: Record<string, string> = {
  fever_under_3mo: "Fever in a baby under 3 months",
  fever_high: "High fever",
  breathing: "Trouble breathing",
  blue_skin: "Bluish skin or lips",
  unresponsive: "Hard to wake or unresponsive",
  seizure: "Possible seizure",
  dehydration: "Signs of dehydration",
  vomiting_bilious: "Green or persistent vomiting",
  head_injury: "Head injury",
  rash_nonblanching: "Rash that doesn’t fade when pressed",
  ingestion: "May have swallowed something",
};

function reasonLabel(reason: string | null): string | null {
  if (!reason) return null;
  return REASON_LABELS[reason] ?? null;
}

export function SeeDoctorBanner() {
  return (
    <div className="mt-2 rounded-xl border border-warn/30 bg-warn/10 px-4 py-3 text-[0.95rem] text-warn">
      Worth mentioning to your pediatrician.
    </div>
  );
}

export function UrgentBanner({
  pediatricianPhone,
  pediatricianName,
}: {
  pediatricianPhone: string | null;
  pediatricianName?: string | null;
}) {
  return (
    <div className="mt-2 rounded-xl border border-warn/50 bg-warn/15 px-4 py-3">
      <p className="font-medium text-warn">
        This is worth a call tonight — don’t wait for morning.
      </p>
      {pediatricianPhone ? (
        <a
          href={`tel:${pediatricianPhone.replace(/[^+\d]/g, "")}`}
          className="mt-3 flex min-h-14 items-center justify-center rounded-xl bg-warn text-lg font-semibold text-background"
        >
          Call {pediatricianName || "your pediatrician"}
        </a>
      ) : (
        <p className="mt-2 text-[0.95rem] text-muted">
          Add your pediatrician’s number in your child’s profile and this
          becomes a one-tap call.
        </p>
      )}
    </div>
  );
}

export function EmergencyCard({
  reason,
  pediatricianPhone,
  pediatricianName,
  onHandled,
  onTellMore,
}: {
  reason: string | null;
  pediatricianPhone: string | null;
  pediatricianName?: string | null;
  onHandled: () => void;
  onTellMore: () => void;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const show911 = reason != null && CALL_911_REASONS.has(reason);
  const label = reasonLabel(reason);

  if (collapsed) {
    return (
      <button
        type="button"
        onClick={() => setCollapsed(false)}
        className="flex min-h-12 w-full items-center justify-between bg-danger px-4 text-left font-semibold text-white"
        aria-expanded={false}
      >
        <span>Emergency guidance — tap to reopen</span>
        <span aria-hidden>▾</span>
      </button>
    );
  }

  return (
    <div
      role="alert"
      className="w-full border-y-2 border-danger bg-danger-deep px-4 py-4"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xl font-bold text-white">
            This needs medical care now
          </p>
          {label && <p className="mt-1 font-medium text-white/90">{label}</p>}
        </div>
        <button
          type="button"
          onClick={() => setCollapsed(true)}
          aria-label="Collapse emergency card"
          className="flex h-12 w-12 shrink-0 items-center justify-center rounded-lg text-white/80"
        >
          ▴
        </button>
      </div>

      <div className="mt-4 flex flex-col gap-3">
        {show911 && (
          <a
            href="tel:911"
            className="flex min-h-16 items-center justify-center rounded-xl bg-danger text-2xl font-bold text-white"
          >
            Call 911
          </a>
        )}
        {pediatricianPhone && (
          <a
            href={`tel:${pediatricianPhone.replace(/[^+\d]/g, "")}`}
            className="flex min-h-14 items-center justify-center rounded-xl border-2 border-white/70 text-lg font-semibold text-white"
          >
            Call {pediatricianName || "Pediatrician"}
          </a>
        )}
        <button
          type="button"
          onClick={onTellMore}
          className="flex min-h-14 items-center justify-center rounded-xl border border-white/40 text-lg font-medium text-white/90"
        >
          Tell me more
        </button>
        <button
          type="button"
          onClick={onHandled}
          className="flex min-h-12 items-center justify-center text-white/70 underline"
        >
          I’ve handled it
        </button>
      </div>
    </div>
  );
}

export function CrisisCard({ onDismiss }: { onDismiss: () => void }) {
  const textLineHref = smsHref(CRISIS_TEXT_LINE);
  return (
    <div
      role="alert"
      className="w-full border-y border-calm bg-calm-deep px-4 py-5"
    >
      <p className="text-lg font-semibold text-foreground">
        You matter too. Right now, in this moment.
      </p>
      <p className="mt-2 leading-relaxed text-foreground/85">
        What you’re feeling is real, and you don’t have to carry it alone.
        Someone kind is awake and ready to listen.
      </p>

      <div className="mt-4 flex flex-col gap-3">
        <div className="grid grid-cols-2 gap-3">
          <a
            href={SUICIDE_CRISIS_LIFELINE.tel}
            className="flex min-h-14 items-center justify-center rounded-xl bg-calm text-lg font-semibold text-background"
          >
            Call 988
          </a>
          <a
            href={SUICIDE_CRISIS_LIFELINE.sms}
            className="flex min-h-14 items-center justify-center rounded-xl border-2 border-calm text-lg font-semibold text-calm"
          >
            Text 988
          </a>
        </div>
        <a
          href={MATERNAL_MENTAL_HEALTH.tel}
          className="flex min-h-14 items-center justify-center rounded-xl border border-calm/60 px-4 text-center font-medium text-foreground"
        >
          Maternal Mental Health — {MATERNAL_MENTAL_HEALTH.display}
        </a>
        {textLineHref && (
          <a
            href={textLineHref}
            className="flex min-h-14 items-center justify-center rounded-xl border border-calm/60 px-4 text-center font-medium text-foreground"
          >
            Text {CRISIS_TEXT_LINE.smsBody} to {CRISIS_TEXT_LINE.display}
          </a>
        )}
        <button
          type="button"
          onClick={onDismiss}
          className="flex min-h-12 items-center justify-center text-foreground/60 underline"
        >
          I’m okay for now
        </button>
      </div>
    </div>
  );
}
