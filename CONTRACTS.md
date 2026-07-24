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

## POST /v1/chat/completions  (OpenAI-compatible, for Vapi custom-LLM — Phase 2)
Same brain/safety pipeline internally. Triage tag stripped before returning; triage side-channel via `safety_events` insert → Supabase Realtime.

## Other endpoints
- `GET /api/v1/me` → `{user_id, email, profile:{...}, children:[...]}`
- `POST /api/v1/children` / `PATCH /api/v1/children/{id}` — fields: name, birth_date, due_date?, feeding_type?, notes?, pediatrician_name?, pediatrician_phone?
- `GET /api/v1/conversations?limit=` / `GET /api/v1/conversations/{id}` (with messages)
- `GET /healthz`

## Passive memory (Phase 3)
Flow: after each completed chat exchange the backend runs extraction (small model, async, from the USER message only) → events land `confirmed=false`. The frontend fetches pending events after the `done` SSE event and renders inline confirm cards. **Unconfirmed events are never injected into prompts** (query-layer invariant). Voice-mode batch confirm (post-call review screen) is Phase 2 scope.

Extraction JSON (backend-internal): `{"events":[{"kind":"feeding|sleep|diaper|symptom|medication|note","summary":"...","occurred_at_offset_minutes":<int ≥0>}]}` — max 5 per message; unknown kinds and empty summaries dropped; failures → empty list.

- `GET /api/v1/events/pending?child_id=&limit=` → `{"events":[{id, child_id, kind, summary, occurred_at, source, confirmed, message_id, created_at}]}` (unconfirmed, newest first)
- `GET /api/v1/events?child_id=&limit=` → same shape (confirmed only, newest first — timeline)
- `POST /api/v1/events/{id}/confirm` → `{"event": {...}}`
- `POST /api/v1/events/confirm-batch` body `{"event_ids":[...]}` → `{"confirmed": n}` (skips foreign/unknown ids)
- `DELETE /api/v1/events/{id}` → 204 (dismiss; 400 if already confirmed — confirmed events are not deletable from the UI in MVP)
- `GET /api/v1/morning-summary?tz_offset_minutes=` → `{"summary": string|null, "night_date"?: "YYYY-MM-DD"}` — tz_offset_minutes = `-new Date().getTimezoneOffset()`. Night window 20:00–06:00 local; null before 06:00, with no night activity, or on summarizer failure. Passive: frontend only calls between 06:00–20:00 local and remembers dismissal per night_date in localStorage. No push notifications.

## Triage tag protocol (backend-internal, documented for tests)
Model must begin EVERY reply with exactly one leading tag:
`<triage level="none|see_doctor|urgent|emergency|crisis" reason="<slug>"/>`
Reason slugs: `fever_under_3mo | fever_high | breathing | blue_skin | unresponsive | seizure | dehydration | vomiting_bilious | head_injury | rash_nonblanching | ingestion | parent_crisis | parent_overwhelm | med_dosing_refusal | general`
Backend buffers ≤120 chars to parse+strip; malformed → log + treat as none + stricter output filter. Severity aggregation: max(rules, classifier, model_tag). Fail direction: always over-escalate, never silently pass.

## Env vars
Frontend (`frontend/.env.local`): `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_API_BASE_URL`
Backend (`backend/.env`): `SUPABASE_URL`, `DATABASE_URL`, `ANTHROPIC_API_KEY`, `CHAT_MODEL=claude-sonnet-5`, `SAFETY_MODEL=claude-haiku-4-5-20251001`, `ALLOWED_ORIGINS`, `ENV`, `LOG_LEVEL`
