"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, apiJson, getApiBaseUrl } from "@/lib/api";
import {
  EVENT_KIND_EMOJI,
  type CareEvent,
  type PendingEventsResponse,
} from "@/lib/types";

function timeAgo(iso: string): string {
  const minutes = Math.max(
    Math.round((Date.now() - new Date(iso).getTime()) / 60000),
    0,
  );
  if (minutes < 1) return "just now";
  if (minutes < 60) return `~${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  return hours === 1 ? "~1 hour ago" : `~${hours} hours ago`;
}

/**
 * Quiet inline confirm cards for passively-extracted events (P3: records are
 * a byproduct of chat, never an obligation). One tap saves; one tap dismisses.
 * Unconfirmed events never influence answers, so ignoring these is always safe.
 */
export function PendingEvents({
  childId,
  refreshKey,
}: {
  childId: string | null;
  refreshKey: number;
}) {
  const [events, setEvents] = useState<CareEvent[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!childId || !getApiBaseUrl()) return;
    let cancelled = false;
    (async () => {
      try {
        const data = await apiJson<PendingEventsResponse>(
          `/api/v1/events/pending?child_id=${encodeURIComponent(childId)}`,
        );
        if (!cancelled) setEvents(data.events);
      } catch {
        // Memory is a bonus, never an error state.
        if (!cancelled) setEvents([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [childId, refreshKey]);

  const remove = useCallback((id: string) => {
    setEvents((prev) => prev.filter((e) => e.id !== id));
  }, []);

  const confirm = useCallback(
    async (event: CareEvent) => {
      remove(event.id);
      try {
        await apiFetch(`/api/v1/events/${event.id}/confirm`, { method: "POST" });
      } catch {
        // Quietly drop; the card is gone either way and nothing unsafe happens.
      }
    },
    [remove],
  );

  const dismiss = useCallback(
    async (event: CareEvent) => {
      remove(event.id);
      try {
        await apiFetch(`/api/v1/events/${event.id}`, { method: "DELETE" });
      } catch {
        // Ignore.
      }
    },
    [remove],
  );

  const saveAll = useCallback(async () => {
    if (busy || events.length === 0) return;
    setBusy(true);
    const ids = events.map((e) => e.id);
    setEvents([]);
    try {
      await apiFetch("/api/v1/events/confirm-batch", {
        method: "POST",
        body: JSON.stringify({ event_ids: ids }),
      });
    } catch {
      // Ignore.
    } finally {
      setBusy(false);
    }
  }, [busy, events]);

  if (events.length === 0) return null;

  return (
    <div className="mt-2 flex flex-col gap-2" aria-label="Remember tonight's events">
      {events.map((event) => (
        <div
          key={event.id}
          className="flex items-center gap-3 rounded-xl border border-border-soft bg-surface px-3 py-2 text-sm"
        >
          <span aria-hidden>{EVENT_KIND_EMOJI[event.kind] ?? "📝"}</span>
          <span className="min-w-0 flex-1 truncate text-muted">
            {event.summary}
            <span className="ml-1 text-xs">({timeAgo(event.occurred_at)})</span>
          </span>
          <button
            type="button"
            onClick={() => confirm(event)}
            className="min-h-11 rounded-lg px-3 font-medium text-foreground"
          >
            Save
          </button>
          <button
            type="button"
            onClick={() => dismiss(event)}
            aria-label={`Dismiss ${event.summary}`}
            className="min-h-11 rounded-lg px-3 text-muted"
          >
            ✕
          </button>
        </div>
      ))}
      {events.length > 2 && (
        <button
          type="button"
          onClick={saveAll}
          disabled={busy}
          className="self-end rounded-lg px-3 py-2 text-sm font-medium text-foreground"
        >
          Save all
        </button>
      )}
    </div>
  );
}
