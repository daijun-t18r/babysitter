"use client";

import { useCallback, useRef, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import {
  maxTriage,
  triageRank,
  type ChatRequest,
  type DeltaEventData,
  type DoneEventData,
  type ErrorEventData,
  type SafetyEventData,
  type StartEventData,
  type TriageLevel,
} from "@/lib/types";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  triage: TriageLevel;
  triageReason: string | null;
}

export interface SafetyState {
  /** Max severity seen this session (never downgrades). */
  sessionLevel: TriageLevel;
  /** Emergency card pinned until the user taps "I've handled it". */
  emergencyActive: boolean;
  emergencyReason: string | null;
  /** Crisis card (indigo) shown independently of emergency. */
  crisisActive: boolean;
  crisisReason: string | null;
  degraded: boolean;
}

export type StreamStatus = "idle" | "streaming" | "error";

const INITIAL_SAFETY: SafetyState = {
  sessionLevel: "none",
  emergencyActive: false,
  emergencyReason: null,
  crisisActive: false,
  crisisReason: null,
  degraded: false,
};

interface SseEvent {
  event: string;
  data: string;
}

function parseSseBlock(block: string): SseEvent | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (dataLines.length === 0) return null;
  return { event, data: dataLines.join("\n") };
}

/**
 * SSE chat client per CONTRACTS.md (start / safety / delta / done / error).
 * Uses fetch + ReadableStream (POST with Authorization header — EventSource
 * cannot do either). Safety aggregation always applies MAX severity, and an
 * emergency never downgrades within the session until explicitly handled.
 */
export function useChatStream(childId: string | null) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streamingText, setStreamingText] = useState("");
  const [status, setStatus] = useState<StreamStatus>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [safety, setSafety] = useState<SafetyState>(INITIAL_SAFETY);
  const conversationIdRef = useRef<string | null>(null);

  const applySafetySignal = useCallback(
    (level: TriageLevel, reason: string | null) => {
      setSafety((prev) => {
        const next: SafetyState = {
          ...prev,
          sessionLevel: maxTriage(prev.sessionLevel, level),
        };
        if (level === "emergency") {
          // Re-pin even if a previous emergency was handled.
          next.emergencyActive = true;
          next.emergencyReason = reason ?? prev.emergencyReason;
        }
        if (level === "crisis") {
          next.crisisActive = true;
          next.crisisReason = reason ?? prev.crisisReason;
        }
        return next;
      });
    },
    [],
  );

  const send = useCallback(
    async (content: string) => {
      const trimmed = content.trim();
      if (!trimmed || !childId || status === "streaming") return;

      setStatus("streaming");
      setErrorMessage(null);
      setStreamingText("");

      const localUserId = `local-user-${Date.now()}`;
      setMessages((prev) => [
        ...prev,
        {
          id: localUserId,
          role: "user",
          content: trimmed,
          triage: "none",
          triageReason: null,
        },
      ]);

      // Per-message triage: max(safety events, done.triage) — over-escalate.
      let messageTriage: TriageLevel = "none";
      let messageReason: string | null = null;
      let assistantText = "";
      let done: DoneEventData | null = null;
      let streamErrored = false;

      const finalizeAssistant = () => {
        if (!assistantText && !done) return;
        const finalTriage = done
          ? maxTriage(done.triage, messageTriage)
          : messageTriage;
        setMessages((prev) => [
          ...prev,
          {
            id: done?.assistant_message_id ?? `local-assistant-${Date.now()}`,
            role: "assistant",
            content: assistantText,
            triage: finalTriage,
            triageReason: messageReason,
          },
        ]);
        setStreamingText("");
      };

      try {
        const body: ChatRequest = {
          conversation_id: conversationIdRef.current,
          child_id: childId,
          content: trimmed,
          input_mode: "text",
        };
        const response = await apiFetch("/api/v1/chat", {
          method: "POST",
          body: JSON.stringify(body),
        });

        if (!response.ok || !response.body) {
          throw new ApiError(
            `The companion is unreachable right now (${response.status}).`,
            response.status,
          );
        }

        const reader = response.body
          .pipeThrough(new TextDecoderStream())
          .getReader();
        let buffer = "";

        const handleEvent = (raw: SseEvent) => {
          switch (raw.event) {
            case "start": {
              const data = JSON.parse(raw.data) as StartEventData;
              conversationIdRef.current = data.conversation_id;
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === localUserId ? { ...m, id: data.user_message_id } : m,
                ),
              );
              break;
            }
            case "safety": {
              const data = JSON.parse(raw.data) as SafetyEventData;
              if (triageRank(data.triage) > triageRank(messageTriage)) {
                messageTriage = data.triage;
                messageReason = data.reason;
              }
              applySafetySignal(data.triage, data.reason);
              break;
            }
            case "delta": {
              const data = JSON.parse(raw.data) as DeltaEventData;
              assistantText += data.text;
              setStreamingText(assistantText);
              break;
            }
            case "done": {
              done = JSON.parse(raw.data) as DoneEventData;
              if (triageRank(done.triage) > triageRank(messageTriage)) {
                messageTriage = done.triage;
              }
              applySafetySignal(done.triage, messageReason);
              if (done.degraded_safety) {
                setSafety((prev) => ({ ...prev, degraded: true }));
              }
              break;
            }
            case "error": {
              const data = JSON.parse(raw.data) as ErrorEventData;
              streamErrored = true;
              setErrorMessage(data.message || "Something went wrong.");
              break;
            }
          }
        };

        for (;;) {
          const { value, done: streamDone } = await reader.read();
          if (streamDone) break;
          buffer += value.replace(/\r\n/g, "\n");
          let separatorIndex = buffer.indexOf("\n\n");
          while (separatorIndex !== -1) {
            const block = buffer.slice(0, separatorIndex);
            buffer = buffer.slice(separatorIndex + 2);
            const parsed = parseSseBlock(block);
            if (parsed) handleEvent(parsed);
            separatorIndex = buffer.indexOf("\n\n");
          }
        }

        finalizeAssistant();
        setStatus(streamErrored ? "error" : "idle");
      } catch (e) {
        // Keep whatever partial reply streamed in — safer than losing
        // escalation copy that may contain emergency numbers.
        finalizeAssistant();
        setErrorMessage(
          e instanceof ApiError
            ? e.message
            : "I lost the connection. Please try again.",
        );
        setStatus("error");
      }
    },
    [childId, status, applySafetySignal],
  );

  const markEmergencyHandled = useCallback(() => {
    setSafety((prev) => ({ ...prev, emergencyActive: false }));
  }, []);

  const dismissCrisis = useCallback(() => {
    setSafety((prev) => ({ ...prev, crisisActive: false }));
  }, []);

  return {
    messages,
    streamingText,
    safety,
    status,
    errorMessage,
    send,
    markEmergencyHandled,
    dismissCrisis,
    conversationId: conversationIdRef.current,
  };
}
