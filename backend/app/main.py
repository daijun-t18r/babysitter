"""App factory. Collaborators are injectable for offline tests."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.ai.chat_service import ChatService
from app.api.deps import SafetyRecorder
from app.api.routes import (
    chat,
    children,
    conversations,
    events,
    health,
    me,
    openai_compat,
    summary,
)
from app.core.config import get_settings
from app.services.memory import MemoryExtractor, MorningSummarizer
from app.services.safety.classifier import SafetyClassifier


def create_app(
    chat_service: ChatService | None = None,
    classifier: SafetyClassifier | None = None,
    safety_recorder: SafetyRecorder | None = None,
    memory_extractor: MemoryExtractor | None = None,
    morning_summarizer: MorningSummarizer | None = None,
) -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())

    app = FastAPI(title="Midnight Companion API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.chat_service = chat_service or ChatService()
    app.state.classifier = classifier or SafetyClassifier()
    app.state.safety_recorder = safety_recorder or SafetyRecorder()
    app.state.memory_extractor = memory_extractor or MemoryExtractor()
    app.state.morning_summarizer = morning_summarizer or MorningSummarizer()
    app.state.morning_cache = {}

    app.include_router(health.router)
    app.include_router(me.router, prefix="/api/v1")
    app.include_router(children.router, prefix="/api/v1")
    app.include_router(conversations.router, prefix="/api/v1")
    app.include_router(chat.router, prefix="/api/v1")
    app.include_router(events.router, prefix="/api/v1")
    app.include_router(summary.router, prefix="/api/v1")
    app.include_router(openai_compat.router)
    return app


app = create_app()
