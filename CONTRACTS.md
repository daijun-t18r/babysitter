# API & Safety Contracts (authoritative for frontend ↔ backend)

Design spec: `~/.gstack/projects/daijun-t18r-babysitter/daijunlu-main-design-20260723-143754.md`
Any change to this file must be reflected in both `frontend/` and `backend/`.

## Auth
- Frontend uses Supabase Auth (`@supabase/ssr`, magic link + Google).
- Every FastAPI request carries `Authorization: Bearer <supabase access_token>` (fetched fresh per request).
- Backend verifies via Supabase JWKS (`{SUPABASE_URL}/auth/v1/.well-known/jwks.json`), validates `exp`, `aud == "authenticated"`, extracts `sub` as `user_id`.

## Triage levels (single source of truth)
`none | see_doctor | urgent | emergency | crisis`

UI mapping:
| level | UI |
|---|---|
| none | normal bubble |
| see_doctor | soft amber inline banner: "worth mentioning to your pediatrician" |
| urgent | amber banner + tap-to-call pediatrician/nurse line (from child profile) |
| emergency | full-width high-contrast red card, pinned until "I've handled it"; buttons: Call 911 (only for 911-grade reasons) / Call Pediatrician / more info. Chat continues underneath. |
| crisis | indigo/purple card (NOT red, must not look medical-emergency): 988 call/text, Maternal Mental Health Hotline 1-833-852-6262, Crisis Text Line HOME→741741 |

Escalation copy in the assistant TEXT always embeds tappable numbers too (double insurance — cards are best-effort).
Sticky rule: once a conversation hits `emergency`, it cannot downgrade in that session until user taps "I've handled it".

## POST /api/v1/chat  (SSE)
Request (JSON):
```json
{
  "conversation_id": null,        // null → create new
  "child_id": "uuid",
  "content": "user text",
  "input_mode": "text"            // "text" | "voice"
}
```
Response: `text/event-stream`, events in order:
```
event: start   data: {"conversation_id":"…","user_message_id":"…"}
event: safety  data: {"triage":"emergency","reason":"fever_under_3mo","source":"rules"}   // may fire multiple times; client applies max severity
event: delta   data: {"text":"…"}                                                        // repeated; triage tag ALREADY stripped
event: done    data: {"assistant_message_id":"…","triage":"emergency","degraded_safety":false}
event: error   data: {"code":"upstream_error","message":"…"}
```
Client: `fetch()` + ReadableStream parsing (NOT EventSource — needs POST + auth header).

## Voice (Phase 2 — Vapi custom LLM)
One brain, two transports: Vapi calls our OpenAI-compatible endpoint below as a custom LLM; text chat keeps its SSE path. Same safety pipeline for both.

### POST /api/v1/voice/session  (Supabase-authed like all /api/v1 routes)
Request: `{"child_id": "uuid"}` — child ownership verified (404 otherwise).
Response: `{"token": "<payload_b64url>.<sig_b64url>", "expires_at": "ISO8601"}`
Token = `base64url(JSON {user_id, child_id, exp})` + `.` + `base64url(HMAC-SHA256(VAPI_SHARED_SECRET, payload_b64url))`; `exp` ≤ 15 min. 503 when `VAPI_SHARED_SECRET` is unset.
Frontend flow: mint token → `vapi.start(NEXT_PUBLIC_VAPI_ASSISTANT_ID, { metadata: { session_token: token } })`; Vapi echoes the metadata into every custom-LLM request. Invalid/expired token → the custom-LLM endpoint refuses (no child data ever flows on an unverified token).

### POST /v1/chat/completions  (called by Vapi)
Auth — both layers required, fail-closed 401:
1. `X-Vapi-Secret` header must equal `VAPI_SHARED_SECRET` (constant-time compare).
2. Session token, read from **`body.metadata.session_token`** (primary documented location), with fallback `body.call.assistantOverrides.metadata.session_token` (the shape Vapi echoes assistant metadata into). Missing/invalid/expired → 401.

Dev-only fallback: `ENV=dev` with `VAPI_SHARED_SECRET` unset serves an anonymous generic-child-context reply (tag strip + dosing filter still apply; nothing persisted or audited). Outside dev an unset secret → 503.

Pipeline (same brain as /api/v1/chat): rules engine on the latest user message (child age from the token-bound profile), prompt = child context + confirmed events, Claude stream, triage tag stripped, dosing-leak filter, `safety_events` audit writes, user+assistant messages persisted with `input_mode='voice'`. Conversation history comes from Vapi's request body (last 21 messages), not the DB. Messages land in one conversation per Vapi call (`call.id` → conversation map, best-effort per-process; falls back to a fresh conversation).

Response: OpenAI `chat.completion.chunk` SSE frames (`data: {...}\n\n`, first chunk `{"role":"assistant"}`, last data chunk `finish_reason:"stop"`, terminated by `data: [DONE]`). `stream=false` → single `chat.completion` JSON.

Triage side-channel: safety events never appear in the OpenAI stream. The PWA subscribes to Supabase Realtime on `safety_events` (added to the `supabase_realtime` publication in migration 002; RLS select policy scopes rows per user) and renders cards from inserts. Escalation numbers embedded in the spoken text are the double insurance.

### Frontend call UI (Phase 2)
Env-gated by `NEXT_PUBLIC_VAPI_PUBLIC_KEY` + `NEXT_PUBLIC_VAPI_ASSISTANT_ID` — either unset hides the call UI entirely (text chat unchanged). Flow: mint session token → `vapi.start(NEXT_PUBLIC_VAPI_ASSISTANT_ID, { metadata: { session_token } })` (Vapi Web SDK merges this into `assistantOverrides`). Live captions from Vapi `message` events (`type="transcript"`; partials replace the in-flight caption, `transcriptType="final"` freezes it). Any voice failure fails INTO text mode with a gentle inline note + tappable 911 — never a dead end.

Realtime triage during calls: while a call is active the frontend subscribes (Supabase browser client) to `postgres_changes` INSERT on `public.safety_events` with filter `user_id=eq.<uid>`, and surfaces `emergency`/`crisis` rows over the call overlay using the SAME EmergencyCard/CrisisCard components (max-severity + sticky-emergency rules unchanged). Row shape (Realtime payload `new`): `{id, user_id, conversation_id, message_id, source, triage_level, matched_rules: text[]|null, classifier_output, child_age_days, created_at}` — client uses `matched_rules[0]` as the reason slug when present.

## Other endpoints
- `GET /api/v1/me` → `{user_id, email, profile:{...}, children:[...]}`
- `DELETE /api/v1/me` → 204 (GDPR account deletion, see Data governance; 502 = nothing deleted, retry later; 503 = deletion not configured). Frontend: `/settings` (gear icon on the history header) requires typing `DELETE`, then calls this, signs out of Supabase, and redirects to `/login?farewell=1`.
- `POST /api/v1/children` / `PATCH /api/v1/children/{id}` — fields: name, birth_date, due_date?, feeding_type?, notes?, pediatrician_name?, pediatrician_phone?
- `GET /api/v1/conversations?limit=` / `GET /api/v1/conversations/{id}` (with messages)
- `GET /healthz`

## Offline (frontend PWA)
- `frontend/public/sw.js` — hand-rolled service worker (no next-pwa), cache name versioned `mc-v1` (bump on any precache/strategy change; activate deletes older versions). Registered by `RegisterServiceWorker` in the root layout: production builds + browsers with SW support only, silent no-op otherwise. `sw.js` is excluded from the auth middleware matcher so registration works logged-out.
- Strategy: precache `/sos` + manifest + icons on install; `/sos` requests (HTML and RSC payloads — Next's `Vary` header keeps them apart) are network-first with cached fallback; `/_next/static/*`, `/icons/*`, and the manifest are cache-first (hashed chunks land in the cache on the first online visit, after which `/sos` renders fully offline); `/api/*`, `/auth*`, non-GET, and cross-origin requests are NEVER intercepted or cached. Emergency numbers are compiled into the bundle (`src/lib/emergency.ts`), never fetched.
- Dev caveats: `next dev` never registers the SW. After serving a production build on localhost, unregister the worker (DevTools → Application → Service Workers) or later dev sessions may get stale cached chunks. Safety pages must never depend on the SW being present — it is an enhancement layer only.

## Passive memory (Phase 3)
Flow: after each completed chat exchange the backend runs extraction (small model, async, from the USER message only) → events land `confirmed=false`. The frontend fetches pending events after the `done` SSE event and renders inline confirm cards. **Unconfirmed events are never injected into prompts** (query-layer invariant). Voice-mode batch confirm (post-call review screen) is Phase 2 scope.

Extraction JSON (backend-internal): `{"events":[{"kind":"feeding|sleep|diaper|symptom|medication|note","summary":"...","occurred_at_offset_minutes":<int ≥0>}]}` — max 5 per message; unknown kinds and empty summaries dropped; failures → empty list.

- `GET /api/v1/events/pending?child_id=&limit=` → `{"events":[{id, child_id, kind, summary, occurred_at, source, confirmed, message_id, created_at}]}` (unconfirmed, newest first)
- `GET /api/v1/events?child_id=&limit=` → same shape (confirmed only, newest first — timeline)
- `POST /api/v1/events/{id}/confirm` → `{"event": {...}}`
- `POST /api/v1/events/confirm-batch` body `{"event_ids":[...]}` → `{"confirmed": n}` (skips foreign/unknown ids)
- `DELETE /api/v1/events/{id}` → 204 (dismiss; 400 if already confirmed — confirmed events are not deletable from the UI in MVP)
- `GET /api/v1/morning-summary?tz_offset_minutes=` → `{"summary": string|null, "night_date"?: "YYYY-MM-DD"}` — tz_offset_minutes = `-new Date().getTimezoneOffset()`. Night window 20:00–06:00 local; null before 06:00, with no night activity, or on summarizer failure. Passive: frontend only calls between 06:00–20:00 local and remembers dismissal per night_date in localStorage. No push notifications.

## Data governance (GDPR Art.17 account deletion — launch gate 4a)
`DELETE /api/v1/me` (Supabase-authed like every /api/v1 route) erases the account and ALL app data:
- The backend makes ONE delete call: Supabase Auth Admin API (`DELETE {SUPABASE_URL}/auth/v1/admin/users/{user_id}`, service-role key, 5s timeout). It performs NO app-side deletes.
- Erasure rides the schema's cascade chain: `auth.users` → `profiles` (ON DELETE CASCADE) → `children`, `conversations`, `events`, `safety_events` (all CASCADE on `profiles.id`/`children.id`) → `messages` (CASCADE on `conversations.id`). What disappears: profile, children, all conversations + messages (text and voice), confirmed + pending events, and the safety-event audit trail.
- Atomicity: the cascade is the only deletion mechanism. Admin call fails → 502 and NOTHING is deleted anywhere (no partial app-side delete can orphan the auth user). `SUPABASE_SERVICE_ROLE_KEY` unset → 503. Identity comes only from the verified token — deleting another user's account is structurally impossible.
- Success → 204; the frontend must sign out locally afterwards (the Supabase session is dead server-side).

## Triage tag protocol (backend-internal, documented for tests)
Model must begin EVERY reply with exactly one leading tag:
`<triage level="none|see_doctor|urgent|emergency|crisis" reason="<slug>"/>`
Reason slugs: `fever_under_3mo | fever_high | breathing | blue_skin | unresponsive | seizure | dehydration | vomiting_bilious | head_injury | rash_nonblanching | ingestion | parent_crisis | parent_overwhelm | med_dosing_refusal | general`
Backend buffers ≤120 chars to parse+strip; malformed → log + treat as none + stricter output filter. Severity aggregation: max(rules, classifier, model_tag). Fail direction: always over-escalate, never silently pass.

## Env vars
Frontend (`frontend/.env.local`): `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_API_BASE_URL`, `NEXT_PUBLIC_VAPI_PUBLIC_KEY` + `NEXT_PUBLIC_VAPI_ASSISTANT_ID` (Phase 2 voice — both unset: call UI hidden entirely, text chat unchanged)
Backend (`backend/.env`): `SUPABASE_URL`, `DATABASE_URL`, `ANTHROPIC_API_KEY`, `CHAT_MODEL=claude-sonnet-5`, `SAFETY_MODEL=claude-haiku-4-5-20251001`, `ALLOWED_ORIGINS`, `ENV`, `LOG_LEVEL`, `VAPI_SHARED_SECRET` (shared with the Vapi assistant's custom-LLM header config AND used to sign voice session tokens; unset = voice disabled outside dev), `SUPABASE_SERVICE_ROLE_KEY` (Auth Admin API, ONLY used by GDPR account deletion; unset = `DELETE /api/v1/me` answers 503)
