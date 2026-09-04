"""FastAPI application factory and entry point.

``create_app`` builds a fully self-contained application: its own settings, its
own :class:`ApplicationState`, its own database.  Nothing is stored at module
scope, which is what lets the test-suite build and tear down complete
applications without leaking state between tests.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.router import build_api_router
from app.api.routes import websocket as websocket_routes
from app.core.config import Settings, get_settings
from app.core.exceptions import CanSentinelError
from app.core.logging import configure_logging, get_logger
from app.core.version import SERVICE_DESCRIPTION, SERVICE_TITLE, __version__
from app.services.state import ApplicationState

logger = get_logger("main")

API_TAGS_METADATA = [
    {"name": "system", "description": "Health, version, status and the audit trail."},
    {"name": "traffic", "description": "Recorded and live CAN traffic, statistics and rate."},
    {"name": "security", "description": "Detected attacks, statistics and triage."},
    {"name": "simulation", "description": "Traffic generator and attack simulation control."},
    {"name": "monitor", "description": "CAN interface and receive-loop lifecycle."},
    {"name": "configuration", "description": "Runtime-tunable detection and retention settings."},
    {"name": "websocket", "description": "Real-time event stream."},
]


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build a configured FastAPI application."""
    settings = settings or get_settings()
    configure_logging(
        level=settings.log_level,
        log_dir=settings.log_dir,
        log_file=settings.log_file,
        max_bytes=settings.log_max_bytes,
        backup_count=settings.log_backup_count,
        json_output=settings.log_json,
        to_file=settings.log_to_file,
        force=True,
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        state = ApplicationState(settings)
        application.state.app_state = state
        try:
            await state.startup()
        except Exception:
            logger.critical("Application startup failed", exc_info=True)
            await state.shutdown()
            raise
        try:
            yield
        finally:
            await state.shutdown()
            application.state.app_state = None

    app = FastAPI(
        title=SERVICE_TITLE,
        description=SERVICE_DESCRIPTION,
        version=__version__,
        lifespan=lifespan,
        openapi_tags=API_TAGS_METADATA,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # CORS is restricted to the configured origins. In production an empty
    # CORS_ORIGINS means "same origin only", which is the safe default when the
    # dashboard is served by a reverse proxy alongside the API.
    origins = settings.cors_origin_list
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "Accept", "Authorization"],
            max_age=600,
        )
    elif not settings.is_production:
        logger.warning("CORS_ORIGINS is empty; browser clients on other origins will be blocked")

    app.include_router(build_api_router(settings.api_prefix))
    app.include_router(websocket_routes.router)

    _install_exception_handlers(app)

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/docs")

    logger.info(
        "Application created",
        extra={
            "context": {
                "version": __version__,
                "environment": settings.app_env,
                "api_prefix": settings.api_prefix,
                "can_interface": settings.can_interface,
            }
        },
    )
    return app


def _install_exception_handlers(app: FastAPI) -> None:
    """Translate internal errors into the documented error envelope."""

    @app.exception_handler(CanSentinelError)
    async def _domain_error(_request: Request, exc: CanSentinelError) -> JSONResponse:
        if exc.status_code >= 500:
            logger.error(
                "Unhandled domain error",
                exc_info=exc,
                extra={"context": {"error_code": exc.error_code, **exc.details}},
            )
        else:
            logger.info(
                "Request rejected",
                extra={"context": {"error_code": exc.error_code, "message": exc.message}},
            )
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload())

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        errors: list[dict[str, Any]] = [
            {
                "field": ".".join(str(part) for part in error.get("loc", ())[1:]) or "body",
                "error": error.get("msg", "invalid value"),
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": "validation_error",
                "message": "the request could not be validated",
                "details": {"errors": errors},
            },
        )

    @app.exception_handler(Exception)
    async def _unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
        # Never leak a stack trace to a client; the detail goes to the log.
        logger.critical("Unhandled exception", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "message": "an unexpected error occurred",
                "details": {},
            },
        )


app = create_app()


def run() -> None:  # pragma: no cover - process entry point
    """Console entry point: ``python -m app.main``."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        log_config=None,
        reload=settings.app_env == "development",
    )


if __name__ == "__main__":  # pragma: no cover
    run()
