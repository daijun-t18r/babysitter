"""Voice session tokens: mint/verify unit tests + the /api/v1/voice/session route."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.core.config import get_settings
from app.core.voice_token import (
    VOICE_TOKEN_TTL_S,
    VoiceTokenError,
    mint_voice_token,
    verify_voice_token,
)
from tests.conftest import TEST_USER_ID, build_app

SECRET = "test-vapi-secret"
CHILD_ID = "33333333-3333-3333-3333-333333333333"
OTHER_USER_ID = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def vapi_secret(monkeypatch):
    """Configure the shared secret on the cached Settings instance."""
    monkeypatch.setattr(get_settings(), "vapi_shared_secret", SECRET)
    return SECRET


def _client(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


class TestTokenRoundtrip:
    def test_mint_then_verify(self):
        token, expires_at = mint_voice_token(TEST_USER_ID, CHILD_ID, SECRET)
        session = verify_voice_token(token, SECRET)
        assert session.user_id == TEST_USER_ID
        assert session.child_id == CHILD_ID
        assert session.exp == int(expires_at.timestamp())

    def test_ttl_capped_at_15_minutes(self):
        now = datetime.now(UTC)
        _, expires_at = mint_voice_token(
            TEST_USER_ID, CHILD_ID, SECRET, ttl_s=3600, now=now
        )
        assert expires_at <= now + timedelta(seconds=VOICE_TOKEN_TTL_S + 1)

    def test_mint_without_secret_refused(self):
        with pytest.raises(VoiceTokenError):
            mint_voice_token(TEST_USER_ID, CHILD_ID, "")


class TestTokenVerifyFailures:
    def test_expired_token(self):
        past = datetime.now(UTC) - timedelta(hours=1)
        token, _ = mint_voice_token(TEST_USER_ID, CHILD_ID, SECRET, ttl_s=60, now=past)
        with pytest.raises(VoiceTokenError, match="expired"):
            verify_voice_token(token, SECRET)

    def test_wrong_secret(self):
        token, _ = mint_voice_token(TEST_USER_ID, CHILD_ID, SECRET)
        with pytest.raises(VoiceTokenError, match="signature"):
            verify_voice_token(token, "some-other-secret")

    def test_tampered_payload(self):
        token, _ = mint_voice_token(TEST_USER_ID, CHILD_ID, SECRET)
        other, _ = mint_voice_token(OTHER_USER_ID, CHILD_ID, SECRET)
        forged = other.split(".")[0] + "." + token.split(".")[1]
        with pytest.raises(VoiceTokenError):
            verify_voice_token(forged, SECRET)

    @pytest.mark.parametrize("garbage", ["", "nodots", "a.b.c", "!!!.???", "a."])
    def test_garbage_tokens(self, garbage):
        with pytest.raises(VoiceTokenError):
            verify_voice_token(garbage, SECRET)

    def test_verify_without_secret_refused(self):
        token, _ = mint_voice_token(TEST_USER_ID, CHILD_ID, SECRET)
        with pytest.raises(VoiceTokenError):
            verify_voice_token(token, "")


class TestVoiceSessionRoute:
    async def test_mints_token_bound_to_user_and_child(
        self, fake_repo, recorder, vapi_secret
    ):
        child = fake_repo.seed_child()
        app = build_app(fake_repo, recorder)
        async with _client(app) as client:
            response = await client.post(
                "/api/v1/voice/session", json={"child_id": str(child.id)}
            )
        assert response.status_code == 200
        data = response.json()
        session = verify_voice_token(data["token"], SECRET)
        assert session.user_id == TEST_USER_ID
        assert session.child_id == str(child.id)
        expires_at = datetime.fromisoformat(data["expires_at"])
        assert expires_at <= datetime.now(UTC) + timedelta(seconds=VOICE_TOKEN_TTL_S + 1)

    async def test_other_users_child_404(self, fake_repo, recorder, vapi_secret):
        fake_repo.seed_profile(OTHER_USER_ID)
        other_child = fake_repo.seed_child(user_id=OTHER_USER_ID)
        app = build_app(fake_repo, recorder)
        async with _client(app) as client:
            response = await client.post(
                "/api/v1/voice/session", json={"child_id": str(other_child.id)}
            )
        assert response.status_code == 404

    async def test_unknown_child_404(self, fake_repo, recorder, vapi_secret):
        app = build_app(fake_repo, recorder)
        async with _client(app) as client:
            response = await client.post(
                "/api/v1/voice/session",
                json={"child_id": "99999999-9999-9999-9999-999999999999"},
            )
        assert response.status_code == 404

    async def test_unconfigured_secret_503(self, fake_repo, recorder):
        child = fake_repo.seed_child()
        app = build_app(fake_repo, recorder)
        async with _client(app) as client:
            response = await client.post(
                "/api/v1/voice/session", json={"child_id": str(child.id)}
            )
        assert response.status_code == 503
