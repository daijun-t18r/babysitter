"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiJson, ApiError } from "@/lib/api";
import {
  getVapiAssistantId,
  getVapiPublicKey,
  loadVapi,
  type VapiClient,
} from "@/lib/vapi";
import type { VoiceSessionRequest, VoiceSessionResponse } from "@/lib/types";

export type VoiceCallStatus = "idle" | "connecting" | "active" | "ended" | "error";

export interface CaptionEntry {
  id: string;
  role: "user" | "assistant";
  text: string;
  final: boolean;
}

/** Vapi `message` event payload — we only consume live transcripts. */
interface VapiTranscriptMessage {
  type?: string;
  role?: string;
  transcriptType?: string;
  transcript?: string;
}

/**
 * Render call captions as a context note for the chat thread ("switch to
 * text" drops the conversation so far into the visible history).
 */
export function formatTranscriptNote(captions: CaptionEntry[]): string {
  const lines = captions
    .map((c) => c.text.trim())
    .map((text, i) =>
      text ? `${captions[i].role === "user" ? "You" : "Companion"}: ${text}` : "",
    )
    .filter(Boolean);
  if (lines.length === 0) return "";
  return `From our call just now:\n${lines.join("\n")}`;
}

// Gentle, non-technical copy: every voice failure lands the parent back in
// text mode with working guidance — never a dead end at 3am.
const GENTLE_FAILURE =
  "I couldn’t keep the call going, but I’m still right here — let’s keep talking by text.";

/**
 * Voice call lifecycle per CONTRACTS.md (identity flow):
 * POST /api/v1/voice/session → {token} → vapi.start(assistantId,
 * {metadata:{session_token}}). Vapi echoes the metadata into the backend's
 * custom-LLM requests, which verifies the token and loads child context.
 */
export function useVoiceCall(childId: string | null) {
  const [status, setStatus] = useState<VoiceCallStatus>("idle");
  const [captions, setCaptions] = useState<CaptionEntry[]>([]);
  const [isMuted, setIsMuted] = useState(false);
  const [assistantSpeaking, setAssistantSpeaking] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const vapiRef = useRef<VapiClient | null>(null);
  const statusRef = useRef<VoiceCallStatus>("idle");
  const captionSeqRef = useRef(0);

  const setStatusTracked = useCallback((next: VoiceCallStatus) => {
    statusRef.current = next;
    setStatus(next);
  }, []);

  const teardown = useCallback(() => {
    const vapi = vapiRef.current;
    vapiRef.current = null;
    setAssistantSpeaking(false);
    setIsMuted(false);
    try {
      vapi?.stop();
    } catch {
      // Defensive — never throw from cleanup.
    }
  }, []);

  // Stop any live call if the page unmounts mid-call.
  useEffect(() => teardown, [teardown]);

  const handleTranscript = useCallback((payload: unknown) => {
    const msg = payload as VapiTranscriptMessage | undefined;
    if (msg?.type !== "transcript" || typeof msg.transcript !== "string") return;
    const text = msg.transcript.trim();
    if (!text) return;
    const role: CaptionEntry["role"] =
      msg.role === "assistant" ? "assistant" : "user";
    const final = msg.transcriptType === "final";
    setCaptions((prev) => {
      const next = [...prev];
      const last = next[next.length - 1];
      // Partials for a speaker replace their in-flight caption; a final
      // freezes it so the next utterance starts a new entry.
      if (last && last.role === role && !last.final) {
        next[next.length - 1] = { ...last, text, final };
      } else {
        captionSeqRef.current += 1;
        next.push({ id: `caption-${captionSeqRef.current}`, role, text, final });
      }
      return next;
    });
  }, []);

  const failIntoText = useCallback(
    (message: string) => {
      teardown();
      setErrorMessage(message);
      setStatusTracked("error");
    },
    [teardown, setStatusTracked],
  );

  const start = useCallback(async () => {
    if (statusRef.current === "connecting" || statusRef.current === "active") {
      return;
    }
    const publicKey = getVapiPublicKey();
    const assistantId = getVapiAssistantId();
    if (!publicKey || !assistantId || !childId) {
      failIntoText(GENTLE_FAILURE);
      return;
    }

    setErrorMessage(null);
    setCaptions([]);
    setIsMuted(false);
    setStatusTracked("connecting");

    try {
      // 1. Mint the short-lived session token (Supabase-authed).
      const body: VoiceSessionRequest = { child_id: childId };
      const session = await apiJson<VoiceSessionResponse>(
        "/api/v1/voice/session",
        { method: "POST", body: JSON.stringify(body) },
      );

      // 2. Load the SDK and wire lifecycle events before starting.
      const Vapi = await loadVapi();
      const vapi = new Vapi(publicKey);
      vapiRef.current = vapi;

      vapi.on("call-start", () => {
        if (vapiRef.current === vapi) setStatusTracked("active");
      });
      vapi.on("call-end", () => {
        if (vapiRef.current !== vapi) return;
        vapiRef.current = null;
        setAssistantSpeaking(false);
        if (statusRef.current !== "error") setStatusTracked("ended");
      });
      vapi.on("speech-start", () => {
        if (vapiRef.current === vapi) setAssistantSpeaking(true);
      });
      vapi.on("speech-end", () => {
        if (vapiRef.current === vapi) setAssistantSpeaking(false);
      });
      vapi.on("message", handleTranscript);
      vapi.on("error", () => {
        if (vapiRef.current !== vapi) return;
        failIntoText(GENTLE_FAILURE);
      });

      // 3. Start with the identity token in assistantOverrides metadata —
      // Vapi echoes it into every custom-LLM request.
      await vapi.start(assistantId, {
        metadata: { session_token: session.token },
      });
    } catch (e) {
      failIntoText(
        e instanceof ApiError && e.code === "no_session"
          ? "You’ve been signed out — sign back in and we can talk."
          : GENTLE_FAILURE,
      );
    }
  }, [childId, failIntoText, handleTranscript, setStatusTracked]);

  const end = useCallback(() => {
    teardown();
    if (statusRef.current === "connecting" || statusRef.current === "active") {
      setStatusTracked("ended");
    }
  }, [teardown, setStatusTracked]);

  const toggleMute = useCallback(() => {
    const vapi = vapiRef.current;
    if (!vapi) return;
    setIsMuted((prev) => {
      const next = !prev;
      try {
        vapi.setMuted(next);
      } catch {
        return prev;
      }
      return next;
    });
  }, []);

  /** Return to idle after the page has consumed the transcript/outcome. */
  const reset = useCallback(() => {
    setCaptions([]);
    setStatusTracked("idle");
  }, [setStatusTracked]);

  return {
    status,
    captions,
    isMuted,
    assistantSpeaking,
    errorMessage,
    start,
    end,
    toggleMute,
    reset,
  };
}
