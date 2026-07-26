// DTOs mirroring CONTRACTS.md — the single source of truth for the API shape.

export const TRIAGE_LEVELS = [
  "none",
  "see_doctor",
  "urgent",
  "emergency",
  "crisis",
] as const;

export type TriageLevel = (typeof TRIAGE_LEVELS)[number];

/** Severity rank; client always applies max severity across signals. */
export function triageRank(level: TriageLevel): number {
  return TRIAGE_LEVELS.indexOf(level);
}

export function maxTriage(a: TriageLevel, b: TriageLevel): TriageLevel {
  return triageRank(a) >= triageRank(b) ? a : b;
}

export type TriageReason =
  | "fever_under_3mo"
  | "fever_high"
  | "breathing"
  | "blue_skin"
  | "unresponsive"
  | "seizure"
  | "dehydration"
  | "vomiting_bilious"
  | "head_injury"
  | "rash_nonblanching"
  | "ingestion"
  | "parent_crisis"
  | "parent_overwhelm"
  | "med_dosing_refusal"
  | "general";

/** Reasons for which the emergency card shows a Call 911 button. */
export const CALL_911_REASONS: ReadonlySet<string> = new Set([
  "breathing",
  "blue_skin",
  "unresponsive",
  "seizure",
]);

export type InputMode = "text" | "voice";

export type FeedingType = "breast" | "formula" | "mixed" | "solids";

// ---- SSE events for POST /api/v1/chat ----

export interface ChatRequest {
  conversation_id: string | null;
  child_id: string;
  content: string;
  input_mode: InputMode;
}

export interface StartEventData {
  conversation_id: string;
  user_message_id: string;
}

export type SafetySource =
  | "rules"
  | "classifier"
  | "model_tag"
  | "output_filter"
  | "manual_review";

export interface SafetyEventData {
  triage: TriageLevel;
  reason: string;
  source: SafetySource;
}

export interface DeltaEventData {
  text: string;
}

export interface DoneEventData {
  /** Null when the backend could not persist the assistant message. */
  assistant_message_id: string | null;
  triage: TriageLevel;
  degraded_safety: boolean;
}

export interface ErrorEventData {
  code: string;
  message: string;
}

// ---- REST resources ----

export interface Profile {
  display_name: string | null;
  phone: string | null;
  disclaimer_accepted_at: string | null;
}

export interface Child {
  id: string;
  name: string;
  birth_date: string;
  due_date: string | null;
  feeding_type: FeedingType | null;
  notes: string | null;
  pediatrician_name: string | null;
  pediatrician_phone: string | null;
}

export interface MeResponse {
  user_id: string;
  email: string | null;
  /** Null if the signup trigger has not created the profile row yet. */
  profile: Profile | null;
  children: Child[];
}

export interface ChildCreateRequest {
  name?: string;
  birth_date: string;
  due_date?: string | null;
  feeding_type?: FeedingType | null;
  notes?: string | null;
  pediatrician_name?: string | null;
  pediatrician_phone?: string | null;
}

export interface ConversationSummary {
  id: string;
  child_id: string | null;
  title: string | null;
  max_triage: TriageLevel;
  created_at: string;
  last_message_at: string;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  input_mode: InputMode;
  triage_level: TriageLevel;
  triage_reason: string | null;
  created_at: string;
}

export interface ConversationDetail extends ConversationSummary {
  messages: Message[];
}

export interface ConversationListResponse {
  conversations: ConversationSummary[];
}

// ---- Passive memory (Phase 3) ----

export type EventKind =
  | "feeding"
  | "sleep"
  | "diaper"
  | "symptom"
  | "medication"
  | "note";

export interface CareEvent {
  id: string;
  child_id: string;
  kind: EventKind;
  summary: string;
  occurred_at: string;
  source: "chat_extraction" | "manual";
  confirmed: boolean;
  message_id: string | null;
  created_at: string;
}

export interface PendingEventsResponse {
  events: CareEvent[];
}

export interface MorningSummaryResponse {
  summary: string | null;
  night_date?: string;
}

// ---- Voice (Phase 2) ----

export interface VoiceSessionRequest {
  child_id: string;
}

/** Short-lived HMAC-signed token binding {user_id, child_id, exp ≤ 15 min}. */
export interface VoiceSessionResponse {
  token: string;
  expires_at: string;
}

/**
 * Row shape of public.safety_events as delivered by Supabase Realtime
 * (postgres_changes INSERT). Used for triage during voice calls; the first
 * matched rule doubles as the reason slug when present.
 */
export interface SafetyEventRow {
  id: string;
  user_id: string;
  conversation_id: string | null;
  message_id: string | null;
  source: string;
  triage_level: TriageLevel;
  matched_rules: string[] | null;
  /** Raw classifier JSON (jsonb) — audit-only, never rendered. */
  classifier_output: unknown;
  child_age_days: number | null;
  created_at: string;
}

export const EVENT_KIND_EMOJI: Record<EventKind, string> = {
  feeding: "🍼",
  sleep: "😴",
  diaper: "🧷",
  symptom: "🌡️",
  medication: "💊",
  note: "📝",
};
