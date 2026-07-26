"use client";

import { useEffect, useRef } from "react";
import type { RealtimeChannel } from "@supabase/supabase-js";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";
import { TRIAGE_LEVELS, type SafetyEventRow, type TriageLevel } from "@/lib/types";

/**
 * While a voice call is active, triage signals arrive as INSERTs on
 * public.safety_events (backend inserts them from the custom-LLM path;
 * migration 002 adds the table to the supabase_realtime publication, and
 * RLS scopes SELECT to the row's user). Emergency/crisis rows surface the
 * same EmergencyCard/CrisisCard over the call overlay via `onSignal`.
 */
export function useCallSafetyEvents(
  active: boolean,
  onSignal: (level: TriageLevel, reason: string | null) => void,
) {
  // Ref so a new callback identity doesn't tear down the subscription.
  const onSignalRef = useRef(onSignal);
  useEffect(() => {
    onSignalRef.current = onSignal;
  }, [onSignal]);

  useEffect(() => {
    if (!active) return;
    const supabase = getSupabaseBrowserClient();
    if (!supabase) return;

    let cancelled = false;
    let channel: RealtimeChannel | null = null;

    (async () => {
      const {
        data: { session },
      } = await supabase.auth.getSession();
      const userId = session?.user?.id;
      if (!userId || cancelled) return;

      channel = supabase
        .channel(`safety-events-${userId}`)
        .on(
          "postgres_changes",
          {
            event: "INSERT",
            schema: "public",
            table: "safety_events",
            filter: `user_id=eq.${userId}`,
          },
          (payload) => {
            const row = payload.new as Partial<SafetyEventRow>;
            const level = row.triage_level;
            if (!level || !(TRIAGE_LEVELS as readonly string[]).includes(level)) {
              return;
            }
            if (level !== "emergency" && level !== "crisis") return;
            onSignalRef.current(level, row.matched_rules?.[0] ?? null);
          },
        )
        .subscribe();
    })();

    return () => {
      cancelled = true;
      if (channel) supabase.removeChannel(channel);
    };
  }, [active]);
}
