const DAY_MS = 24 * 60 * 60 * 1000;

/**
 * Human age string for the chat header. Uses corrected age when a due date
 * is set (born 3+ weeks early), matching how pediatric guidance is applied.
 */
export function formatChildAge(
  birthDate: string,
  dueDate?: string | null,
  now: Date = new Date(),
): string {
  const anchor = dueDate ? new Date(dueDate) : new Date(birthDate);
  const days = Math.max(0, Math.floor((now.getTime() - anchor.getTime()) / DAY_MS));
  const corrected = dueDate ? " (adjusted)" : "";

  if (days < 14) return `${days} day${days === 1 ? "" : "s"} old${corrected}`;
  if (days < 84) {
    const weeks = Math.floor(days / 7);
    return `${weeks} week${weeks === 1 ? "" : "s"} old${corrected}`;
  }
  const months = Math.floor(days / 30.44);
  if (months < 24) return `${months} month${months === 1 ? "" : "s"} old${corrected}`;
  const years = Math.floor(months / 12);
  return `${years} year${years === 1 ? "" : "s"} old${corrected}`;
}

/** A quiet, hour-aware greeting. Never chirpy; it is probably 3am. */
export function nightGreeting(now: Date = new Date()): string {
  const hour = now.getHours();
  if (hour >= 22 || hour < 2) return "Late night. I'm here — take your time.";
  if (hour >= 2 && hour < 5) return "The deep middle of the night. You're not doing this alone.";
  if (hour >= 5 && hour < 9) return "Early morning. You made it through the night.";
  if (hour >= 9 && hour < 17) return "Hi. I'm here whenever you need me.";
  return "Evening. I'm here if tonight gets long.";
}
