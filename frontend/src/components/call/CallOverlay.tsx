"use client";

import { useEffect, useRef, type ReactNode } from "react";
import type { CaptionEntry } from "@/components/call/useVoiceCall";

function MicIcon({ muted }: { muted: boolean }) {
  return (
    <svg
      width="26"
      height="26"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0" />
      <path d="M12 18v3" />
      {muted && <path d="M4 4l16 16" />}
    </svg>
  );
}

/**
 * Full-screen call UI: warm-black background, soft pulsing indicator,
 * large live captions, one-handed bottom controls. No sounds — the voice
 * itself is the only audio. Safety cards (emergency/crisis) render above
 * everything via `safetyCards`.
 */
export function CallOverlay({
  childName,
  status,
  captions,
  isMuted,
  assistantSpeaking,
  onToggleMute,
  onSwitchToText,
  onEnd,
  safetyCards,
}: {
  childName: string | null;
  status: "connecting" | "active";
  captions: CaptionEntry[];
  isMuted: boolean;
  assistantSpeaking: boolean;
  onToggleMute: () => void;
  onSwitchToText: () => void;
  onEnd: () => void;
  safetyCards?: ReactNode;
}) {
  const connecting = status === "connecting";
  const captionAnchorRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    captionAnchorRef.current?.scrollIntoView({ block: "end" });
  }, [captions]);

  const statusLine = connecting
    ? "Connecting…"
    : assistantSpeaking
      ? "Speaking"
      : isMuted
        ? "Muted"
        : "Listening";

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Voice call"
      className="fixed inset-0 z-50 flex flex-col bg-background"
    >
      {/* Triage cards from Supabase Realtime pin over the call, same
          components as text mode. */}
      {safetyCards}

      <div className="safe-top px-4 pt-4 text-center">
        <p className="font-semibold">
          {childName ? `About ${childName}` : "Midnight Companion"}
        </p>
        <p className="mt-1 text-sm text-muted" aria-live="polite">
          {statusLine}
        </p>
      </div>

      {/* Soft pulsing indicator — brighter while the companion speaks. */}
      <div className="flex items-center justify-center pb-2 pt-6">
        <div className="relative flex h-24 w-24 items-center justify-center">
          <div
            className={
              assistantSpeaking
                ? "absolute inset-0 rounded-full bg-accent/25 animate-ping"
                : "absolute inset-0 rounded-full bg-accent/10 animate-pulse"
            }
          />
          <div
            className={`relative h-16 w-16 rounded-full transition-colors duration-300 ${
              connecting
                ? "bg-accent-soft"
                : assistantSpeaking
                  ? "bg-accent"
                  : "bg-accent/50"
            }`}
          />
        </div>
      </div>

      {/* Live captions — large and readable in the dark. */}
      <main
        className="flex-1 overflow-y-auto px-5 py-4"
        aria-label="Live captions"
      >
        {connecting && captions.length === 0 && (
          <p className="mt-6 text-center text-lg text-muted">
            One moment — I’m picking up…
          </p>
        )}
        <div className="flex flex-col gap-4">
          {captions.map((caption) => (
            <div
              key={caption.id}
              className={
                caption.role === "user" ? "flex justify-end" : "flex justify-start"
              }
            >
              <p
                className={
                  caption.role === "user"
                    ? `max-w-[85%] text-right text-lg leading-relaxed text-muted ${
                        caption.final ? "" : "opacity-70"
                      }`
                    : `max-w-[92%] text-xl leading-relaxed text-foreground ${
                        caption.final ? "" : "opacity-80"
                      }`
                }
              >
                {caption.text}
              </p>
            </div>
          ))}
        </div>
        <div ref={captionAnchorRef} />
      </main>

      {/* One-handed bottom controls — all ≥48px targets. */}
      <footer className="safe-bottom px-6 pb-6 pt-3">
        <div className="flex items-end justify-between">
          <button
            type="button"
            onClick={onToggleMute}
            aria-label={isMuted ? "Unmute" : "Mute"}
            aria-pressed={isMuted}
            className={`flex h-16 w-16 flex-col items-center justify-center rounded-full border ${
              isMuted
                ? "border-accent bg-accent text-background"
                : "border-border-soft bg-surface text-foreground"
            }`}
          >
            <MicIcon muted={isMuted} />
          </button>

          <button
            type="button"
            onClick={onSwitchToText}
            className="flex min-h-16 min-w-24 flex-col items-center justify-center rounded-2xl border border-border-soft bg-surface px-4 text-foreground"
          >
            <svg
              width="24"
              height="24"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden
            >
              <path d="M21 12a8 8 0 0 1-8 8H5l-2 2V12a8 8 0 0 1 8-8h2a8 8 0 0 1 8 8z" />
            </svg>
            <span className="mt-1 text-sm">Switch to text</span>
          </button>

          <button
            type="button"
            onClick={onEnd}
            aria-label="End call"
            className="flex h-16 w-16 items-center justify-center rounded-full bg-danger text-white"
          >
            <svg
              width="28"
              height="28"
              viewBox="0 0 24 24"
              fill="currentColor"
              aria-hidden
              style={{ transform: "rotate(135deg)" }}
            >
              <path d="M6.6 10.8a15 15 0 0 0 6.6 6.6l2.2-2.2a1 1 0 0 1 1-.24 11.4 11.4 0 0 0 3.6.58 1 1 0 0 1 1 1V20a1 1 0 0 1-1 1A17 17 0 0 1 3 4a1 1 0 0 1 1-1h3.5a1 1 0 0 1 1 1 11.4 11.4 0 0 0 .57 3.6 1 1 0 0 1-.25 1z" />
            </svg>
          </button>
        </div>
        <p className="mt-4 text-center text-xs text-muted">
          Not medical advice. In an emergency call{" "}
          <a href="tel:911" className="font-semibold text-foreground underline">
            911
          </a>
          .
        </p>
      </footer>
    </div>
  );
}
