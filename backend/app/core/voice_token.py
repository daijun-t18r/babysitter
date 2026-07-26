"""Short-lived HMAC voice session tokens (Phase 2).

The logged-in PWA calls POST /api/v1/voice/session, which mints a token
binding {user_id, child_id, exp}. The frontend passes it through Vapi
assistant metadata; Vapi echoes it into every custom-llm request, where
/v1/chat/completions verifies it and loads the child context.

Format: `base64url(json_payload) "." base64url(hmac_sha256(secret, payload))`.
Hand-rolled on stdlib hmac/hashlib — no new dependencies. Verification is
constant-time (hmac.compare_digest) and fails closed: any structural problem,
bad signature, or expiry raises VoiceTokenError.
"""

import base64
import binascii
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime

VOICE_TOKEN_TTL_S = 15 * 60  # hard cap per the design spec: exp ≤ 15 minutes


class VoiceTokenError(Exception):
    """Any mint/verify failure. Callers translate to 401/503; never leak details."""


@dataclass(frozen=True)
class VoiceSession:
    user_id: str
    child_id: str
    exp: int  # unix seconds


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _sign(payload_b64: str, secret: str) -> str:
    digest = hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).digest()
    return _b64url_encode(digest)


def mint_voice_token(
    user_id: str,
    child_id: str,
    secret: str,
    ttl_s: int = VOICE_TOKEN_TTL_S,
    now: datetime | None = None,
) -> tuple[str, datetime]:
    """Returns (token, expires_at). ttl is capped at VOICE_TOKEN_TTL_S."""
    if not secret:
        raise VoiceTokenError("no signing secret configured")
    ttl_s = min(ttl_s, VOICE_TOKEN_TTL_S)
    now_ts = int((now or datetime.now(UTC)).timestamp())
    exp = now_ts + ttl_s
    payload = json.dumps(
        {"user_id": str(user_id), "child_id": str(child_id), "exp": exp},
        separators=(",", ":"),
    )
    payload_b64 = _b64url_encode(payload.encode())
    token = f"{payload_b64}.{_sign(payload_b64, secret)}"
    return token, datetime.fromtimestamp(exp, UTC)


def verify_voice_token(
    token: str, secret: str, now: datetime | None = None
) -> VoiceSession:
    """Signature first (constant-time), then structure, then expiry."""
    if not secret:
        raise VoiceTokenError("no signing secret configured")
    payload_b64, _, signature = token.partition(".")
    if not payload_b64 or not signature:
        raise VoiceTokenError("malformed token")
    if not hmac.compare_digest(signature, _sign(payload_b64, secret)):
        raise VoiceTokenError("bad signature")
    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except (ValueError, binascii.Error) as exc:
        raise VoiceTokenError("undecodable payload") from exc
    user_id = payload.get("user_id") if isinstance(payload, dict) else None
    child_id = payload.get("child_id") if isinstance(payload, dict) else None
    exp = payload.get("exp") if isinstance(payload, dict) else None
    if not isinstance(user_id, str) or not isinstance(child_id, str) or not isinstance(exp, int):
        raise VoiceTokenError("missing claims")
    now_ts = int((now or datetime.now(UTC)).timestamp())
    if exp <= now_ts:
        raise VoiceTokenError("expired")
    return VoiceSession(user_id=user_id, child_id=child_id, exp=exp)
