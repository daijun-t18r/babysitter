"use client";

import type { ChatMessage } from "@/components/chat/useChatStream";
import { SeeDoctorBanner, UrgentBanner } from "@/components/chat/SafetyCard";

export function MessageBubble({
  message,
  pediatricianPhone,
  pediatricianName,
}: {
  message: ChatMessage;
  pediatricianPhone?: string | null;
  pediatricianName?: string | null;
}) {
  // Client-side context note (e.g. a voice-call transcript) — centered,
  // quiet, clearly not a chat bubble.
  if (message.role === "note") {
    return (
      <div className="flex justify-center">
        <div className="max-w-[92%] whitespace-pre-wrap rounded-xl border border-border-soft bg-surface/60 px-4 py-3 text-sm leading-relaxed text-muted">
          {message.content}
        </div>
      </div>
    );
  }

  const isUser = message.role === "user";

  return (
    <div className={isUser ? "flex justify-end" : "flex justify-start"}>
      <div className={`max-w-[85%] ${isUser ? "" : "w-full"}`}>
        <div
          className={
            isUser
              ? "rounded-3xl rounded-br-lg bg-accent-soft px-4 py-3 leading-relaxed"
              : "rounded-3xl rounded-bl-lg bg-surface px-4 py-3 leading-relaxed"
          }
        >
          <p className="whitespace-pre-wrap">{message.content}</p>
        </div>
        {!isUser && message.triage === "see_doctor" && <SeeDoctorBanner />}
        {!isUser && message.triage === "urgent" && (
          <UrgentBanner
            pediatricianPhone={pediatricianPhone ?? null}
            pediatricianName={pediatricianName}
          />
        )}
      </div>
    </div>
  );
}

export function StreamingBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-start">
      <div className="w-full max-w-[85%]">
        <div className="rounded-3xl rounded-bl-lg bg-surface px-4 py-3 leading-relaxed">
          {text ? (
            <p className="whitespace-pre-wrap">{text}</p>
          ) : (
            <p className="text-muted" aria-label="Thinking">
              …
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
