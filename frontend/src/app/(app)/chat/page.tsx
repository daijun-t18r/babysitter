"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";
import { apiJson, ApiError, getApiBaseUrl } from "@/lib/api";
import { formatChildAge, nightGreeting } from "@/lib/age";
import type { Child, MeResponse } from "@/lib/types";
import { ChatHeader } from "@/components/chat/ChatHeader";
import { Composer } from "@/components/chat/Composer";
import { EmergencySheet } from "@/components/chat/EmergencySheet";
import { MessageBubble, StreamingBubble } from "@/components/chat/MessageBubble";
import { MorningSummaryCard } from "@/components/chat/MorningSummaryCard";
import { PendingEvents } from "@/components/chat/PendingEvents";
import { QuickActions } from "@/components/chat/QuickActions";
import { CrisisCard, EmergencyCard } from "@/components/chat/SafetyCard";
import { useChatStream } from "@/components/chat/useChatStream";

type LoadState = "loading" | "ready" | "unconfigured" | "error";

const noopSubscribe = () => () => {};

/** Hour-aware greeting, empty during SSR to avoid a clock hydration mismatch. */
function useNightGreeting(): string {
  return useSyncExternalStore(noopSubscribe, nightGreeting, () => "");
}

export default function ChatPage() {
  const router = useRouter();
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [child, setChild] = useState<Child | null>(null);
  const [emergencySheetOpen, setEmergencySheetOpen] = useState(false);
  const greeting = useNightGreeting();

  const {
    messages,
    streamingText,
    safety,
    status,
    errorMessage,
    send,
    markEmergencyHandled,
    dismissCrisis,
  } = useChatStream(child?.id ?? null);

  const scrollAnchorRef = useRef<HTMLDivElement>(null);

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
        const firstChild = me.children[0];
        if (!firstChild || !me.profile?.disclaimer_accepted_at) {
          router.replace("/onboarding");
          return;
        }
        setChild(firstChild);
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
  }, [router]);

  useEffect(() => {
    scrollAnchorRef.current?.scrollIntoView({ block: "end" });
  }, [messages, streamingText]);

  const childAge = child ? formatChildAge(child.birth_date, child.due_date) : null;
  const showQuickActions = messages.length === 0 && status === "idle";
  // Refetch pending extracted events after each completed exchange.
  const assistantCount = messages.filter((m) => m.role === "assistant").length;

  return (
    <div className="flex h-dvh flex-col">
      <ChatHeader
        childName={child?.name ?? null}
        childAge={childAge}
        greeting={greeting}
        onOpenEmergency={() => setEmergencySheetOpen(true)}
      />

      {/* Pinned safety cards — emergency stays until "I’ve handled it". */}
      {safety.emergencyActive && (
        <EmergencyCard
          reason={safety.emergencyReason}
          pediatricianPhone={child?.pediatrician_phone ?? null}
          pediatricianName={child?.pediatrician_name}
          onHandled={markEmergencyHandled}
          onTellMore={() =>
            send("Tell me more about what I should do right now.")
          }
        />
      )}
      {safety.crisisActive && <CrisisCard onDismiss={dismissCrisis} />}

      {loadState === "ready" && <MorningSummaryCard />}

      <main className="flex-1 overflow-y-auto px-4 py-4">
        {loadState === "loading" && (
          <p className="mt-10 text-center text-muted">One moment…</p>
        )}
        {loadState === "unconfigured" && (
          <p className="mt-10 text-center text-muted">
            The companion isn’t connected in this environment.
          </p>
        )}
        {loadState === "error" && (
          <div className="mt-10 text-center text-muted">
            <p>I couldn’t reach the companion just now.</p>
            <p className="mt-2">
              If something feels wrong with your baby, trust yourself — call
              your pediatrician, or{" "}
              <a href="tel:911" className="font-semibold text-foreground underline">
                911
              </a>{" "}
              in an emergency.
            </p>
          </div>
        )}

        {loadState === "ready" && messages.length === 0 && (
          <div className="mt-8 text-center text-muted">
            <p className="text-lg">
              I’m here. What’s happening with {child?.name || "your baby"}?
            </p>
          </div>
        )}

        <div className="flex flex-col gap-3">
          {messages.map((message) => (
            <MessageBubble
              key={message.id}
              message={message}
              pediatricianPhone={child?.pediatrician_phone}
              pediatricianName={child?.pediatrician_name}
            />
          ))}
          {status === "streaming" && <StreamingBubble text={streamingText} />}
        </div>

        {loadState === "ready" && status === "idle" && (
          <PendingEvents childId={child?.id ?? null} refreshKey={assistantCount} />
        )}

        {errorMessage && status === "error" && (
          <div className="mt-3 rounded-xl border border-border-soft bg-surface px-4 py-3 text-muted">
            <p>{errorMessage}</p>
            <p className="mt-1 text-sm">
              Worried right now? Call your pediatrician or{" "}
              <a href="tel:911" className="font-semibold text-foreground underline">
                911
              </a>
              .
            </p>
          </div>
        )}

        <div ref={scrollAnchorRef} />
      </main>

      <footer className="safe-bottom border-t border-border-soft bg-background pb-2">
        {loadState === "ready" && showQuickActions && (
          <div className="pt-3">
            <QuickActions onPick={send} />
          </div>
        )}
        <Composer
          onSend={send}
          disabled={loadState !== "ready" || status === "streaming"}
        />
        <p className="px-4 pt-2 text-center text-xs text-muted">
          Not medical advice. In an emergency call 911.
        </p>
      </footer>

      <EmergencySheet
        open={emergencySheetOpen}
        onClose={() => setEmergencySheetOpen(false)}
        pediatricianName={child?.pediatrician_name}
        pediatricianPhone={child?.pediatrician_phone}
      />
    </div>
  );
}
