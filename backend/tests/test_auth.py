"""JWT verification and the dev-mode bypass gate. No network: JWKS is faked."""

import time
from types import SimpleNamespace

import httpx
import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core import auth as auth_module
from app.core.config import get_settings
from tests.conftest import TEST_USER_ID, FakeRecorder, FakeRepo, build_app


@pytest.fixture(scope="module")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def fake_jwks(rsa_key, monkeypatch):
    public_key = rsa_key.public_key()

    class FakeJWKSClient:
        def get_signing_key_from_jwt(self, token):
            return SimpleNamespace(key=public_key)

    monkeypatch.setattr(auth_module, "get_jwks_client", lambda: FakeJWKSClient())


@pytest.fixture
def settings_env(monkeypatch):
    """Set env vars and refresh the cached Settings; restores cache after."""

    def apply(**env: str) -> None:
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        get_settings.cache_clear()

    yield apply
    get_settings.cache_clear()


def make_token(rsa_key, sub=TEST_USER_ID, aud="authenticated", expires_in=3600):
    now = int(time.time())
    return pyjwt.encode(
        {"sub": sub, "aud": aud, "exp": now + expires_in, "iat": now, "email": "p@example.com"},
        rsa_key,
        algorithm="RS256",
    )


@pytest.fixture
def auth_app():
    """App with real auth dependency; repo faked so /api/v1/me works offline."""
    fake_repo = FakeRepo()
    fake_repo.seed_profile()
    app = build_app(fake_repo, FakeRecorder())
    del app.dependency_overrides[auth_module.get_current_user]  # use real auth
    return app


async def _get_me(app, headers):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/api/v1/me", headers=headers)


class TestTokenVerification:
    async def test_valid_token_accepted(self, auth_app, fake_jwks, rsa_key):
        token = make_token(rsa_key)
        response = await _get_me(auth_app, {"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        body = response.json()
        assert body["user_id"] == TEST_USER_ID
        assert body["email"] == "p@example.com"
        assert body["profile"] is not None

    async def test_expired_token_rejected(self, auth_app, fake_jwks, rsa_key):
        token = make_token(rsa_key, expires_in=-100)
        response = await _get_me(auth_app, {"Authorization": f"Bearer {token}"})
        assert response.status_code == 401

    async def test_bad_audience_rejected(self, auth_app, fake_jwks, rsa_key):
        token = make_token(rsa_key, aud="not-authenticated")
        response = await _get_me(auth_app, {"Authorization": f"Bearer {token}"})
        assert response.status_code == 401

    async def test_missing_token_rejected(self, auth_app, fake_jwks):
        response = await _get_me(auth_app, {})
        assert response.status_code == 401

    async def test_garbage_token_rejected(self, auth_app, fake_jwks):
        response = await _get_me(auth_app, {"Authorization": "Bearer not.a.jwt"})
        assert response.status_code == 401


class TestDevBypass:
    async def test_bypass_works_in_dev(self, auth_app, settings_env):
        settings_env(ENV="dev")
        response = await _get_me(auth_app, {"X-Dev-User-Id": TEST_USER_ID})
        assert response.status_code == 200
        assert response.json()["user_id"] == TEST_USER_ID

    async def test_bypass_ignored_outside_dev(self, auth_app, settings_env, fake_jwks):
        settings_env(ENV="prod")
        response = await _get_me(auth_app, {"X-Dev-User-Id": TEST_USER_ID})
        assert response.status_code == 401

    async def test_real_token_still_works_outside_dev(
        self, auth_app, settings_env, fake_jwks, rsa_key
    ):
        settings_env(ENV="prod")
        token = make_token(rsa_key)
        response = await _get_me(auth_app, {"Authorization": f"Bearer {token}"})
        assert response.status_code == 200


class TestVerifyFunction:
    def test_injectable_jwks_client(self, rsa_key):
        public_key = rsa_key.public_key()

        class InjectedClient:
            def get_signing_key_from_jwt(self, token):
                return SimpleNamespace(key=public_key)

        token = make_token(rsa_key, sub="user-42")
        user = auth_module.verify_supabase_jwt(token, jwks_client=InjectedClient())
        assert user.user_id == "user-42"
        assert user.email == "p@example.com"
