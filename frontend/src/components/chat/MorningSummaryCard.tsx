"use client";

import { useEffect, useState } from "react";
import { apiJson, getApiBaseUrl } from "@/lib/api";
import type { MorningSummaryResponse } from "@/lib/types";

const DISMISS_KEY = "morning-summary-dismissed";

/**
 * The passive morning-after card: only fetched between 06:00 and 20:00 local,
 * shown once per night_date, dismissal remembered in localStorage. No push,
 * no badge — it simply exists when the parent naturally comes back.
 */
export function MorningSummaryCard() {
  const [data, setData] = useState<MorningSummaryResponse | null>(null);

  useEffect(() => {
    if (!getApiBaseUrl()) return;
    const hour = new Date().getHours();
    if (hour < 6 || hour >= 20) return;

    let cancelled = false;
    (async () => {
      try {
        const tzOffset = -new Date().getTimezoneOffset();
        const result = await apiJson<MorningSummaryResponse>(
          `/api/v1/morning-summary?tz_offset_minutes=${tzOffset}`,
        );
        if (cancelled || !result.summary || !result.night_date) return;
        if (localStorage.getItem(DISMISS_KEY) === result.night_date) return;
        setData(result);
      } catch {
        // A missing card is always fine.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (!data?.summary) return null;

  const dismiss = () => {
    if (data.night_date) localStorage.setItem(DISMISS_KEY, data.night_date);
    setData(null);
  };

  return (
    <div className="mx-4 mt-3 rounded-2xl border border-border-soft bg-surface px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-medium text-muted">About last night</p>
        <button
          type="button"
          onClick={dismiss}
          aria-label="Dismiss morning summary"
          className="min-h-11 min-w-11 rounded-lg text-muted"
        >
          ✕
        </button>
      </div>
      <p className="text-[15px] leading-relaxed">{data.summary}</p>
    </div>
  );
}
