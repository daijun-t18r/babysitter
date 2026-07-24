"use client";

import Link from "next/link";

export function ChatHeader({
  childName,
  childAge,
  greeting,
  onOpenEmergency,
}: {
  childName: string | null;
  childAge: string | null;
  greeting: string;
  onOpenEmergency: () => void;
}) {
  return (
    <header className="safe-top border-b border-border-soft bg-background/95 px-4 pb-3 backdrop-blur">
      <div className="flex items-center justify-between pt-2">
        <button
          type="button"
          onClick={onOpenEmergency}
          aria-label="Emergency numbers"
          className="flex h-12 w-12 items-center justify-center rounded-full bg-surface text-accent"
        >
          {/* shield icon */}
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
            <path d="M12 2l8 4v6c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10V6l8-4z" />
            <path d="M9.5 12.5l2 2 3.5-4" />
          </svg>
        </button>

        <div className="min-w-0 flex-1 px-3 text-center">
          {childName ? (
            <>
              <p className="truncate font-semibold">{childName}</p>
              {childAge && <p className="text-sm text-muted">{childAge}</p>}
            </>
          ) : (
            <p className="font-semibold">Midnight Companion</p>
          )}
        </div>

        <Link
          href="/history"
          aria-label="Past nights"
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
            <circle cx="12" cy="12" r="9" />
            <path d="M12 7v5l3 2" />
          </svg>
        </Link>
      </div>
      {greeting && <p className="mt-2 text-center text-sm text-muted">{greeting}</p>}
    </header>
  );
}
