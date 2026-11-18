"""Backend-only entrypoint for МедВед.Код2."""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from app.api.routes import router
from app.core.config import Settings
from app.core.rate_limit import LocalRateLimiter
from app.integrations.max_core import MaxCoreClient
from app.services.sessions import SessionService
from app.integrations.groq import GroqClient, GroqSettings, MockGroqClient, SymptomExtractor


def create_app(settings: Settings | None = None, max_core: MaxCoreClient | None = None,
               extractor: SymptomExtractor | None = None) -> FastAPI:
    """Construct an isolated backend. Dependencies may be injected in tests."""
    settings = settings or Settings.from_env()
    settings.validate()
    app = FastAPI(
        title="МедВед.Код2 backend",
        description="Демонстрационный API: не предназначен для реальной медицинской консультации.",
        version="0.1.0",
    )
    app.state.settings = settings
    app.state.max_core = max_core or MaxCoreClient(settings)
    extractor = extractor or SymptomExtractor(
        GroqClient(GroqSettings.from_env()) if settings.nlp_mode == "live" else MockGroqClient()
    )
    app.state.sessions = SessionService(settings.survey_ttl_seconds, extractor=extractor)
    app.state.launch_limiter = LocalRateLimiter()
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware, allow_origins=list(settings.cors_origins),
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
            allow_credentials=False,
        )

    @app.middleware("http")
    async def harden_headers(request: Request, call_next):
        if request.headers.get("content-length"):
            try:
                if int(request.headers["content-length"]) > 16384:
                    return JSONResponse(status_code=413, content={"detail": "request_too_large"})
            except ValueError:
                return JSONResponse(status_code=400, content={"detail": "invalid_request_length"})
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "frame-ancestors " + " ".join(settings.frame_ancestors)
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        # Do not echo raw body or medical content as Pydantic error "input".
        return JSONResponse(status_code=422, content={"detail": "invalid_request_schema"})

    app.include_router(router)
    return app


app = create_app()
