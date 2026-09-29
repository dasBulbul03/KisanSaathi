"""Application entrypoint.

Wires the FastAPI app together: middleware, CORS, the v1 router tree, the error
envelope and the operational endpoints. Import as ``app.main:app``.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1 import api_router
from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import bind_request_context, clear_request_context, get_logger
from app.db.session import check_database, get_engine

logger = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
ERROR_RESPONSES: dict[int | str, dict[str, list]] = {
    400: {"description": "The request could not be processed"},
    401: {"description": "Missing or invalid credentials"},
    403: {"description": "Authenticated but not permitted"},
    404: {"description": "Resource not found"},
    409: {"description": "Conflicting state, e.g. an invalid status transition"},
    422: {"description": "Validation failed"},
    429: {"description": "Rate limited"},
}


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Report database reachability on boot and on shutdown.

    The schema is deliberately not created here: schema changes are Alembic's
    and the seeder's job, not a side effect of starting the process.
    """
    try:
        engine = get_engine()
        logger.info(
            "app.startup",
            environment=settings.ENVIRONMENT,
            dialect=engine.dialect.name,
            demo_mode=settings.DEMO_MODE,
        )
    except Exception as exc:  # pragma: no cover - misconfigured database URL
        logger.error("app.startup.database_unavailable", error=str(exc))
        raise
    yield
    logger.info("app.shutdown")


def create_app() -> FastAPI:
    """Build the ASGI application.

    A factory rather than a module-level singleton so tests can construct an app
    with different settings without importing side effects.
    """
    settings.validate_runtime()

    app = FastAPI(
        title=settings.PROJECT_NAME,
        description=settings.PROJECT_DESCRIPTION,
        version=settings.APP_VERSION,
        openapi_url="/openapi.json",
        docs_url="/docs" if settings.DOCS_ENABLED else None,
        redoc_url="/redoc" if settings.DOCS_ENABLED else None,
        openapi_tags=[
            {"name": "auth", "description": "Registration, login, tokens and profile"},
            {"name": "markets", "description": "Commodities, mandis, prices and trends"},
            {"name": "lots", "description": "Produce listings a seller has published"},
            {"name": "demands", "description": "Buyer requirements seeking produce"},
            {"name": "matches", "description": "Ranked lot/demand compatibility"},
            {"name": "offers", "description": "Buyer offers and seller negotiation"},
            {"name": "orders", "description": "Accepted trades and their lifecycle"},
            {"name": "logistics", "description": "Transport requests, quotes and tracking"},
            {"name": "storage", "description": "Godown and cold storage capacity"},
            {"name": "quality", "description": "Inspection and grading"},
            {"name": "payments", "description": "Settlement between buyers and sellers"},
            {"name": "grievances", "description": "Dispute tickets and resolution"},
            {"name": "notifications", "description": "In-app notifications"},
            {"name": "ai", "description": "Grounded assistant and price discovery"},
            {"name": "dashboards", "description": "Role-specific summary screens"},
            {"name": "admin", "description": "Administration and audit"},
            {"name": "system", "description": "Health and readiness"},
        ],
        lifespan=lifespan,
        responses=ERROR_RESPONSES,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[REQUEST_ID_HEADER],
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Attach a request id and log one line per request.

        The id is taken from an inbound ``X-Request-ID`` when present so a trace
        survives across services, and is echoed back so a caller can quote it in
        a bug report.
        """
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        request.state.request_id = request_id
        clear_request_context()
        bind_request_context(request_id=request_id, path=request.url.path)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "request.unhandled_exception",
                method=request.method,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            raise
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers[REQUEST_ID_HEADER] = request_id
        log = logger.warning if response.status_code >= 500 else logger.info
        log(
            "request.completed",
            method=request.method,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        clear_request_context()
        return response

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        """Map every expected failure onto the documented error envelope.

        Expected failures are logged at warning level without a stack trace;
        the trace belongs on the 500 path, not on "you sent a bad state".
        """
        logger.warning(
            "request.app_error",
            code=exc.code,
            status_code=exc.status_code,
            detail=exc.message,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(request, code=exc.code, message=exc.message, details=exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Flatten pydantic errors into ``field -> messages`` for the client."""
        field_errors: dict[str, list[str]] = {}
        for error in exc.errors():
            location = [str(part) for part in error.get("loc", ()) if part != "body"]
            field_errors[".".join(location) or "body"] = [error.get("msg", "Invalid value")]
        logger.info("request.validation_error", fields=list(field_errors))
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_error_body(
                request,
                code="VALIDATION_ERROR",
                message="One or more fields are invalid.",
                field_errors=field_errors,
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        """Keep framework-raised 404/405 responses in the same envelope."""
        code = {
            401: "UNAUTHENTICATED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
        }.get(exc.status_code, "HTTP_ERROR")
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(request, code=code, message=str(exc.detail)),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        """Last resort. Log the trace, tell the client only the request id.

        In production the message is deliberately generic so an internal error
        cannot leak a column name, a query or a file path to a stranger.
        """
        logger.exception("request.unhandled_exception", error=str(exc))
        message = (
            str(exc)
            if settings.DEBUG
            else "An unexpected error occurred. Quote the request id when reporting this."
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_body(request, code="INTERNAL_ERROR", message=message),
        )

    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    @app.get("/health", tags=["system"], summary="Liveness and readiness")
    def health() -> dict[str, object]:
        """Report process and database health.

        Liveness for a load balancer is ``status == "ok"``; ``database`` tells an
        operator whether the instance is actually usable.
        """
        database_ok = check_database()
        return {
            "status": "ok" if database_ok else "degraded",
            "service": settings.PROJECT_NAME,
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
            "database": "up" if database_ok else "down",
            "demo_mode": settings.DEMO_MODE,
        }

    @app.get("/ready", tags=["system"], summary="Readiness probe")
    def ready() -> JSONResponse:
        """Return 503 until the database answers, so traffic drains not crashes."""
        database_ok = check_database()
        return JSONResponse(
            status_code=200 if database_ok else 503,
            content={"ready": database_ok, "database": "up" if database_ok else "down"},
        )

    @app.get("/", tags=["system"], include_in_schema=False)
    def root() -> dict[str, str]:
        return {
            "service": settings.PROJECT_NAME,
            "version": settings.APP_VERSION,
            "docs": "/docs" if settings.DOCS_ENABLED else "disabled",
            "api": settings.API_V1_PREFIX,
        }

    return app


def _error_body(
    request: Request,
    *,
    code: str,
    message: str,
    details: dict | None = None,
    field_errors: dict[str, list[str]] | None = None,
) -> dict:
    error: dict[str, object] = {"code": code, "message": message}
    if field_errors:
        error["field_errors"] = field_errors
    elif details:
        error["details"] = details
    return {
        "success": False,
        "error": error,
        "request_id": getattr(request.state, "request_id", None),
    }


app = create_app()
