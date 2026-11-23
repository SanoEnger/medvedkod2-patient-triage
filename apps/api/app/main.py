"""Backend entrypoint. Use app.run_api for verified HTTPS."""
import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.chat_routes import router as chat_router
from app.api.routes import router
from app.api.voice_routes import MAX_AUDIO_BYTES, TRANSCRIPTION_PATH, router as voice_router
from app.core.config import Settings
from app.core.encryption import JsonCipher
from app.core.observability import RequestLoggingMiddleware, configure_logging, event
from app.core.rate_limit import LocalRateLimiter
from app.db.engine import create_engine
from app.db.models import Base
from app.db.repository import delete_expired_sessions
from app.db.safety_catalog import verify_runtime_catalog
from app.db.survey_store import PostgresSurveyStore
from app.integrations.chat_agent import ChatAgent, MockChatAgent
from app.integrations.groq import (
    GroqClient,
    GroqSettings,
    MockGroqClient,
    SymptomExtractor,
)
from app.integrations.max_core import MaxCoreClient
from app.services.chat import ChatService
from app.services.sessions import SessionService


async def expire_sessions(factory, cipher: JsonCipher) -> None:
    while True:
        await asyncio.sleep(60)
        try:
            async with factory.begin() as db:
                await delete_expired_sessions(db, cipher=cipher)
        except (SQLAlchemyError, OSError):
            logging.getLogger(__name__).warning("Session cleanup temporarily unavailable")


def create_app(
    settings: Settings | None = None, max_core: MaxCoreClient | None = None,
    *, session_service: SessionService | None = None, extractor: SymptomExtractor | None = None,
    chat_service: ChatService | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    configure_logging()
    settings.validate()
    extractor = extractor or SymptomExtractor(GroqClient(GroqSettings.from_env()) if settings.nlp_mode == "live" else MockGroqClient())
    engine = None
    if session_service is None:
        cipher = JsonCipher.from_file(settings.data_encryption_key_file)
        engine = create_engine(settings=settings)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        chat_agent = ChatAgent(GroqClient(GroqSettings.from_env())) if settings.nlp_mode == "live" else MockChatAgent()
        session_service = SessionService(settings.survey_ttl_seconds,
                                        PostgresSurveyStore(factory, cipher, settings.demo_mode), extractor=extractor,
                                        analyst=chat_agent, analysis_source="groq" if settings.nlp_mode == "live" else "mock")
        chat_service = chat_service or ChatService(factory, cipher, chat_agent,
            ttl_seconds=settings.survey_ttl_seconds, demo_mode=settings.demo_mode)

    @asynccontextmanager
    async def lifespan(app):
        task = None
        try:
            if engine is not None:
                async with factory() as db:
                    for table in Base.metadata.sorted_tables:
                        await db.execute(select(table).limit(0))
                    await verify_runtime_catalog(db, cipher)
                task = asyncio.create_task(expire_sessions(factory, cipher))
            event("application.ready", mode=settings.nlp_mode)
            yield
        finally:
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            if engine is not None:
                await engine.dispose()
            event("application.stopped")

    app = FastAPI(title="МедВед.Код2 backend",
                  description="Демонстрационный API для синтетических данных.",
                  version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.sessions = session_service
    app.state.chat = chat_service
    app.state.max_core = max_core or MaxCoreClient(settings)
    app.state.launch_limiter = LocalRateLimiter()
    app.state.voice_lock = asyncio.Lock()
    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                           allow_methods=["GET", "POST", "DELETE"],
                           allow_headers=["Authorization", "Content-Type"],
                           expose_headers=["X-Request-ID"],
                           allow_credentials=False)

    @app.middleware("http")
    async def harden_headers(request: Request, call_next):
        headers = {
            "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "frame-ancestors " + " ".join(settings.frame_ancestors),
        }
        if request.url.scheme != "https":
            return JSONResponse(status_code=426, content={"detail": "https_required"}, headers=headers)
        headers["Strict-Transport-Security"] = "max-age=31536000"
        if request.headers.get("content-length"):
            try:
                limit = MAX_AUDIO_BYTES if request.url.path == TRANSCRIPTION_PATH else 16384
                if int(request.headers["content-length"]) > limit:
                    return JSONResponse(status_code=413, content={"detail": "request_too_large"}, headers=headers)
            except ValueError:
                return JSONResponse(status_code=400, content={"detail": "invalid_request_length"}, headers=headers)
        response = await call_next(request)
        response.headers.update(headers)
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"detail": "invalid_request_schema"})

    app.include_router(router)
    app.include_router(chat_router)
    app.include_router(voice_router)
    app.add_middleware(RequestLoggingMiddleware)
    return app
