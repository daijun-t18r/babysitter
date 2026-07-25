"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiJson, ApiError, getApiBaseUrl } from "@/lib/api";
import {
  EVENT_KIND_EMOJI,
  type CareEvent,
  type ConversationListResponse,
  type ConversationSummary,
  type MeResponse,
  type PendingEventsResponse,
  type TriageLevel,
} from "@/lib/types";

type LoadState = "loading" | "ready" | "unconfigured" | "error";

const DAY_MS = 24 * 60 * 60 * 1000;

/** A "night" runs noon → noon; shift by 12h and take the date. */
function nightKey(iso: string): string {
  const shifted = new Date(new Date(iso).getTime() - 12 * 60 * 60 * 1000);
  return shifted.toISOString().slice(0, 10);
}

function nightLabel(key: string): string {
  const todayKey = nightKey(new Date().toISOString());
  const keyDate = new Date(`${key}T12:00:00`);
  const todayDate = new Date(`${todayKey}T12:00:00`);
  const diffDays = Math.round((todayDate.getTime() - keyDate.getTime()) / DAY_MS);
  if (diffDays === 0) return "Tonight";
  if (diffDays === 1) return "Last night";
  return `Night of ${keyDate.toLocaleDateString("en-US", {
    month: "long",
    day: "numeric",
  })}`;
}

function TriageBadge({ level }: { level: TriageLevel }) {
  if (level === "none") return null;
  const styles: Record<Exclude<TriageLevel, "none">, string> = {
    see_doctor: "bg-warn/15 text-warn",
    urgent: "bg-warn/25 text-warn",
    emergency: "bg-danger-deep text-danger",
    crisis: "bg-calm-deep text-calm",
  };
  const labels: Record<Exclude<TriageLevel, "none">, string> = {
    see_doctor: "See doctor",
    urgent: "Urgent",
    emergency: "Emergency",
    crisis: "Crisis support",
  };
  return (
    <span
      className={`shrink-0 rounded-full px-3 py-1 text-sm font-medium ${styles[level]}`}
    >
      {labels[level]}
    </span>
  );
}

export default function HistoryPage() {
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [events, setEvents] = useState<CareEvent[]>([]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      if (!getApiBaseUrl()) {
        setLoadState("unconfigured");
        return;
      }
      try {
        const data = await apiJson<ConversationListResponse>(
          "/api/v1/conversations?limit=100",
        );
        if (cancelled) return;
        setConversations(data.conversations);
        setLoadState("ready");
      } catch (e) {
        if (cancelled) return;
        setLoadState(
          e instanceof ApiError && e.code === "not_configured"
            ? "unconfigured"
            : "error",
        );
      }
      // Timeline is best-effort decoration; its failure never breaks history.
      try {
        const me = await apiJson<MeResponse>("/api/v1/me");
        const childId = me.children[0]?.id;
        if (!childId || cancelled) return;
        const data = await apiJson<PendingEventsResponse>(
          `/api/v1/events?child_id=${encodeURIComponent(childId)}`,
        );
        if (!cancelled) setEvents(data.events);
      } catch {
        // Ignore.
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const eventGroups = new Map<string, CareEvent[]>();
  for (const event of events) {
    const key = nightKey(event.occurred_at);
    const bucket = eventGroups.get(key);
    if (bucket) bucket.push(event);
    else eventGroups.set(key, [event]);
  }

  const groups = new Map<string, ConversationSummary[]>();
  for (const conversation of conversations) {
    const key = nightKey(conversation.last_message_at ?? conversation.created_at);
    const bucket = groups.get(key);
    if (bucket) bucket.push(conversation);
    else groups.set(key, [conversation]);
  }
  const sortedKeys = [...groups.keys()].sort((a, b) => (a < b ? 1 : -1));

  return (
    <main className="safe-top safe-bottom mx-auto flex w-full max-w-md flex-1 flex-col px-4 py-4">
      <div className="flex items-center gap-3">
        <Link
          href="/chat"
          aria-label="Back to chat"
          className="flex h-12 w-12 items-center justify-center rounded-full bg-surface text-muted"
        >
          <svg
            width="22"
            height="22"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden
          >
            <path d="M15 5l-7 7 7 7" />
          </svg>
        </Link>
        <h1 className="text-xl font-semibold">Past nights</h1>
      </div>

      {loadState === "loading" && (
        <p className="mt-10 text-center text-muted">One moment…</p>
      )}
      {loadState === "unconfigured" && (
        <p className="mt-10 text-center text-muted">
          History isn’t available in this environment.
        </p>
      )}
      {loadState === "error" && (
        <p className="mt-10 text-center text-muted">
          Couldn’t load your history right now.
        </p>
      )}
      {loadState === "ready" && conversations.length === 0 && (
        <p className="mt-10 text-center text-muted">
          No nights recorded yet. That’s a good thing.
        </p>
      )}

      {sortedKeys.map((key) => (
        <section key={key} className="mt-6">
          <h2 className="text-sm font-medium uppercase tracking-wide text-muted">
            {nightLabel(key)}
          </h2>
          <ul className="mt-2 flex flex-col gap-2">
            {groups.get(key)!.map((conversation) => (
              <li
                key={conversation.id}
                className="flex min-h-16 items-center justify-between gap-3 rounded-2xl bg-surface px-4 py-3"
              >
                <div className="min-w-0">
                  <p className="truncate font-medium">
                    {conversation.title || "Late-night conversation"}
                  </p>
                  <p className="text-sm text-muted">
                    {new Date(conversation.last_message_at).toLocaleTimeString(
                      "en-US",
                      { hour: "numeric", minute: "2-digit" },
                    )}
                  </p>
                </div>
                <TriageBadge level={conversation.max_triage} />
              </li>
            ))}
          </ul>
          {(eventGroups.get(key)?.length ?? 0) > 0 && (
            <ul className="mt-2 flex flex-col gap-1 px-1">
              {eventGroups.get(key)!.map((event) => (
                <li key={event.id} className="flex items-center gap-2 text-sm text-muted">
                  <span aria-hidden>{EVENT_KIND_EMOJI[event.kind] ?? "📝"}</span>
                  <span className="min-w-0 flex-1 truncate">{event.summary}</span>
                  <span className="shrink-0 text-xs">
                    {new Date(event.occurred_at).toLocaleTimeString("en-US", {
                      hour: "numeric",
                      minute: "2-digit",
                    })}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      ))}
    </main>
  );
}
