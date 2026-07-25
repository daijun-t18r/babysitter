"use client";

import Link from "next/link";

const QUICK_PROMPTS: { label: string; message: string }[] = [
  { label: "Won't stop crying", message: "My baby won't stop crying and I don't know why." },
  { label: "Won't sleep", message: "My baby won't sleep. What can I try?" },
  { label: "Fever", message: "I think my baby has a fever." },
  { label: "Feeding trouble", message: "We're having trouble with feeding right now." },
  { label: "Spit-up", message: "My baby just spit up and I'm not sure if it's normal." },
];

/** Big thumb-zone chips (>=64pt) for one-handed 3am starts. */
export function QuickActions({
  onPick,
  disabled,
}: {
  onPick: (message: string) => void;
  disabled?: boolean;
}) {
  return (
    <div className="px-4 pb-2">
      <div className="grid grid-cols-2 gap-3">
        {QUICK_PROMPTS.map((prompt) => (
          <button
            key={prompt.label}
            type="button"
            disabled={disabled}
            onClick={() => onPick(prompt.message)}
            className="min-h-16 rounded-2xl border border-border-soft bg-surface px-3 text-left font-medium leading-snug disabled:opacity-50"
          >
            {prompt.label}
          </button>
        ))}
        <Link
          href="/sos"
          className="col-span-2 flex min-h-16 items-center justify-center rounded-2xl bg-accent-soft px-4 text-lg font-medium text-accent"
        >
          I need a break
        </Link>
      </div>
    </div>
  );
}
