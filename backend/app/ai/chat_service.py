"""Streaming wrapper around the Anthropic messages API.

Thinking stays disabled (never passed): the voice latency budget requires
first-token in well under a second. The client is injectable for tests.
"""

from collections.abc import AsyncIterator
from typing import Any

from app.core.config import get_settings

MAX_TOKENS = 700


class ChatService:
    def __init__(
        self,
        client: Any | None = None,
        model: str | None = None,
        max_tokens: int = MAX_TOKENS,
    ) -> None:
        self._client = client
        self._model = model
        self._max_tokens = max_tokens

    @property
    def model(self) -> str:
        return self._model or get_settings().chat_model

    def _get_client(self) -> Any:
        if self._client is None:
            from anthropic import AsyncAnthropic

            settings = get_settings()
            self._client = AsyncAnthropic(
                api_key=settings.anthropic_api_key or "anthropic-dev-placeholder"
            )
        return self._client

    async def stream_text(
        self,
        *,
        system: list[dict[str, Any]],
        messages: list[dict[str, Any]],
    ) -> AsyncIterator[str]:
        async with self._get_client().messages.stream(
            model=self.model,
            max_tokens=self._max_tokens,
            system=system,
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                yield text
