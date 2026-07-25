"""/v1/chat/completions (Vapi custom LLM): auth layers, OpenAI chunk format,
tag stripping, safety audit + voice persistence — all offline."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.core.config import get_settings
from app.core.voice_token import mint_voice_token
from tests.conftest import TEST_USER_ID, build_app

SECRET = "test-vapi-secret"
TAG_NONE = '<triage level="none" reason="general"/>'

BENIGN_CHUNKS = [
    TAG_NONE,
    "Try putting her down drowsy but awake, with white noise on. ",
    "This stretch of night is the hardest one and it does pass.",
]


@pytest.fixture
def vapi_secret(monkeypatch):
    monkeypatch.setattr(get_settings(), "vapi_shared_secret", SECRET)
    return SECRET


def _client(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _token(child_id) -> str:
    token, _ = mint_voice_token(TEST_USER_ID, str(child_id), SECRET)
    return token


def _body(content: str, child_id, *, stream=True, call_id=None, token=None, **extra):
    body: dict = {
        "model": "vapi-model",
        "stream": stream,
        "messages": [
            {"role": "system", "content": "vapi assistant prompt"},
            {"role": "user", "content": content},
        ],
        "metadata": {"session_token": token or _token(child_id)},
        **extra,
    }
    if call_id:
        body["call"] = {"id": call_id}
    return body


async def _post(app, body, secret=SECRET):
    headers = {"X-Vapi-Secret": secret} if secret is not None else {}
    async with _client(app) as client:
        return await client.post("/v1/chat/completions", json=body, headers=headers)


def parse_chunks(raw: str) -> list[dict]:
    """OpenAI SSE frames: `data: {...}` blocks terminated by `data: [DONE]`."""
    frames = []
    for line in raw.split("\n\n"):
        line = line.strip()
        if not line:
            continue
        assert line.startswith("data: ")
        payload = line[len("data: ") :]
        frames.append(payload if payload == "[DONE]" else json.loads(payload))
    return frames


class TestAuth:
    async def test_missing_secret_header_401(self, fake_repo, recorder, vapi_secret):
        child = fake_repo.seed_child()
        app = build_app(fake_repo, recorder, chunks=BENIGN_CHUNKS)
        response = await _post(app, _body("hello", child.id), secret=None)
        assert response.status_code == 401

    async def test_wrong_secret_401(self, fake_repo, recorder, vapi_secret):
        child = fake_repo.seed_child()
        app = build_app(fake_repo, recorder, chunks=BENIGN_CHUNKS)
        response = await _post(app, _body("hello", child.id), secret="wrong-secret")
        assert response.status_code == 401

    async def test_missing_session_token_401(self, fake_repo, recorder, vapi_secret):
        child = fake_repo.seed_child()
        app = build_app(fake_repo, recorder, chunks=BENIGN_CHUNKS)
        body = _body("hello", child.id)
        del body["metadata"]
        response = await _post(app, body)
        assert response.status_code == 401

    async def test_bad_session_token_401(self, fake_repo, recorder, vapi_secret):
        child = fake_repo.seed_child()
        app = build_app(fake_repo, recorder, chunks=BENIGN_CHUNKS)
        response = await _post(app, _body("hello", child.id, token="not.atoken"))
        assert response.status_code == 401

    async def test_expired_session_token_401(self, fake_repo, recorder, vapi_secret):
        child = fake_repo.seed_child()
        app = build_app(fake_repo, recorder, chunks=BENIGN_CHUNKS)
        past = datetime.now(UTC) - timedelta(hours=1)
        expired, _ = mint_voice_token(TEST_USER_ID, str(child.id), SECRET, now=past)
        response = await _post(app, _body("hello", child.id, token=expired))
        assert response.status_code == 401

    async def test_unconfigured_secret_503_outside_dev(
        self, fake_repo, recorder, monkeypatch
    ):
        child = fake_repo.seed_child()
        monkeypatch.setattr(get_settings(), "env", "prod")
        app = build_app(fake_repo, recorder, chunks=BENIGN_CHUNKS)
        response = await _post(app, _body("hello", child.id, token="x.y"))
        assert response.status_code == 503

    async def test_token_in_call_assistant_overrides_accepted(
        self, fake_repo, recorder, vapi_secret
    ):
        child = fake_repo.seed_child()
        app = build_app(fake_repo, recorder, chunks=BENIGN_CHUNKS)
        body = _body("hello", child.id)
        token = body.pop("metadata")["session_token"]
        body["call"] = {"id": "call-1", "assistantOverrides": {"metadata": {"session_token": token}}}
        response = await _post(app, body)
        assert response.status_code == 200


class TestStreamingFormat:
    async def test_chunk_format_and_tag_stripped(self, fake_repo, recorder, vapi_secret):
        child = fake_repo.seed_child()
        app = build_app(fake_repo, recorder, chunks=BENIGN_CHUNKS)
        response = await _post(app, _body("she won't settle", child.id))
        assert response.status_code == 200

        frames = parse_chunks(response.text)
        assert frames[-1] == "[DONE]"
        chunks = frames[:-1]
        assert all(c["object"] == "chat.completion.chunk" for c in chunks)
        assert all(c["model"] == "vapi-model" for c in chunks)
        assert len({c["id"] for c in chunks}) == 1

        assert chunks[0]["choices"][0]["delta"] == {"role": "assistant"}
        assert chunks[-1]["choices"][0]["finish_reason"] == "stop"

        text = "".join(
            c["choices"][0]["delta"].get("content", "") for c in chunks
        )
        assert "<triage" not in text
        assert "drowsy but awake" in text

    async def test_non_streaming_fallback(self, fake_repo, recorder, vapi_secret):
        child = fake_repo.seed_child()
        app = build_app(fake_repo, recorder, chunks=BENIGN_CHUNKS)
        response = await _post(app, _body("she won't settle", child.id, stream=False))
        assert response.status_code == 200
        data = response.json()
        assert data["object"] == "chat.completion"
        content = data["choices"][0]["message"]["content"]
        assert "<triage" not in content
        assert "drowsy but awake" in content
        assert data["choices"][0]["finish_reason"] == "stop"

    async def test_no_user_message_400(self, fake_repo, recorder, vapi_secret):
        child = fake_repo.seed_child()
        app = build_app(fake_repo, recorder, chunks=BENIGN_CHUNKS)
        body = _body("x", child.id)
        body["messages"] = [{"role": "system", "content": "prompt only"}]
        response = await _post(app, body)
        assert response.status_code == 400


class TestSafetyPipeline:
    async def test_red_flag_writes_safety_event_and_persists_voice_messages(
        self, fake_repo, recorder, vapi_secret
    ):
        child = fake_repo.seed_child(
            birth_date=datetime.now(UTC).date() - timedelta(days=56)
        )
        app = build_app(fake_repo, recorder, chunks=BENIGN_CHUNKS)
        response = await _post(app, _body("her rectal temp is 100.6", child.id))
        assert response.status_code == 200

        rules_events = [e for e in recorder.events if e["source"] == "rules"]
        assert rules_events and rules_events[0]["triage_level"] == "emergency"
        assert "fever_under_3mo" in rules_events[0]["matched_rules"]
        assert rules_events[0]["user_id"] == TEST_USER_ID

        users = [m for m in fake_repo.messages if m.role == "user"]
        assert users and users[0].input_mode == "voice"
        [assistant] = fake_repo.assistant_messages()
        assert assistant.input_mode == "voice"
        assert assistant.triage_level == "emergency"
        assert "<triage" not in assistant.content

        # No safety frames leak into the OpenAI stream (cards go via Realtime).
        for frame in parse_chunks(response.text)[:-1]:
            assert "triage" not in json.dumps(frame["choices"][0]["delta"])

    async def test_unknown_child_in_token_404(self, fake_repo, recorder, vapi_secret):
        app = build_app(fake_repo, recorder, chunks=BENIGN_CHUNKS)
        response = await _post(
            app, _body("hello", "99999999-9999-9999-9999-999999999999")
        )
        assert response.status_code == 404


class TestConversationReuse:
    async def test_same_call_id_reuses_conversation(self, fake_repo, recorder, vapi_secret):
        child = fake_repo.seed_child()
        app = build_app(fake_repo, recorder, chunks=BENIGN_CHUNKS)
        await _post(app, _body("first turn", child.id, call_id="call-abc"))
        await _post(app, _body("second turn", child.id, call_id="call-abc"))
        assert len(fake_repo.conversations) == 1

    async def test_different_call_ids_get_fresh_conversations(
        self, fake_repo, recorder, vapi_secret
    ):
        child = fake_repo.seed_child()
        app = build_app(fake_repo, recorder, chunks=BENIGN_CHUNKS)
        await _post(app, _body("turn", child.id, call_id="call-1"))
        await _post(app, _body("turn", child.id, call_id="call-2"))
        assert len(fake_repo.conversations) == 2


class TestDevAnonymousMode:
    async def test_dev_without_secret_serves_generic_reply_without_persistence(
        self, fake_repo, recorder
    ):
        # ENV=dev default + no secret: anonymous mode, no token needed.
        app = build_app(fake_repo, recorder, chunks=BENIGN_CHUNKS)
        body = {
            "stream": True,
            "messages": [{"role": "user", "content": "hello"}],
        }
        response = await _post(app, body, secret=None)
        assert response.status_code == 200
        text = "".join(
            c["choices"][0]["delta"].get("content", "")
            for c in parse_chunks(response.text)[:-1]
        )
        assert "<triage" not in text
        assert "drowsy but awake" in text
        assert fake_repo.messages == []
        assert recorder.events == []
