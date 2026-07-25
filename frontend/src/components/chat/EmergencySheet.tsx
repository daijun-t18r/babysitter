"use client";

import { ALL_EMERGENCY_RESOURCES, smsHref } from "@/lib/emergency";

/**
 * Bottom sheet with every emergency number. All data is compiled into the
 * bundle — this must keep working with no network at 3am.
 */
export function EmergencySheet({
  open,
  onClose,
  pediatricianName,
  pediatricianPhone,
}: {
  open: boolean;
  onClose: () => void;
  pediatricianName?: string | null;
  pediatricianPhone?: string | null;
}) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex flex-col justify-end">
      <button
        type="button"
        aria-label="Close emergency numbers"
        onClick={onClose}
        className="absolute inset-0 bg-black/60"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Emergency numbers"
        className="safe-bottom relative max-h-[85vh] overflow-y-auto rounded-t-3xl bg-surface-raised px-5 pb-6 pt-4"
      >
        <div className="mx-auto mb-4 h-1.5 w-10 rounded-full bg-border-soft" />
        <h2 className="text-xl font-semibold">Emergency numbers</h2>
        <p className="mt-1 text-sm text-muted">
          These work even when you’re offline.
        </p>

        <ul className="mt-4 flex flex-col gap-3">
          {pediatricianPhone && (
            <li>
              <a
                href={`tel:${pediatricianPhone.replace(/[^+\d]/g, "")}`}
                className="flex min-h-16 flex-col justify-center rounded-2xl bg-accent-soft px-4"
              >
                <span className="font-semibold text-accent">
                  {pediatricianName || "Your pediatrician"}
                </span>
                <span className="text-sm text-muted">{pediatricianPhone}</span>
              </a>
            </li>
          )}
          {ALL_EMERGENCY_RESOURCES.map((resource) => {
            const href = resource.tel ?? smsHref(resource);
            return (
              <li key={resource.id}>
                <a
                  href={href ?? undefined}
                  className={`flex min-h-16 flex-col justify-center rounded-2xl px-4 ${
                    resource.id === "emergency_911"
                      ? "bg-danger-deep"
                      : "bg-surface"
                  }`}
                >
                  <span
                    className={`font-semibold ${
                      resource.id === "emergency_911"
                        ? "text-danger"
                        : "text-foreground"
                    }`}
                  >
                    {resource.label}
                  </span>
                  <span className="text-sm text-muted">
                    {resource.description}
                  </span>
                </a>
              </li>
            );
          })}
        </ul>

        <button
          type="button"
          onClick={onClose}
          className="mt-5 min-h-14 w-full rounded-xl border border-border-soft text-lg text-muted"
        >
          Close
        </button>
      </div>
    </div>
  );
}
