from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.database import check_db_connection, close_db_connections, create_all_tables
from app.utils.exceptions import VIMSBaseException

# Import all models to ensure they are registered on Base.metadata
import app.models  # noqa: F401

settings = get_settings()
logger = logging.getLogger("vims")

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)


# ── Lifespan ───────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application startup / shutdown handler.

    On startup:
    - Verify database connectivity.
    - Create any missing tables (useful for development; in production use
      Alembic migrations instead).

    On shutdown:
    - Gracefully dispose the connection pool.
    """
    logger.info("Starting %s v%s [%s]", settings.APP_NAME, settings.APP_VERSION, settings.ENVIRONMENT)

    # Verify DB is reachable
    db_ok = await check_db_connection()
    if not db_ok:
        logger.critical("Database is unreachable — startup aborted.")
        raise RuntimeError("Cannot connect to the database.")

    logger.info("Database connection verified.")

    # Auto-create tables in non-production environments
    if settings.ENVIRONMENT != "production":
        await create_all_tables()
        logger.info("Database tables ensured.")

    yield  # application runs here

    logger.info("Shutting down — disposing database connections...")
    await close_db_connections()
    logger.info("Shutdown complete.")


# ── App factory ────────────────────────────────────────────────────────────────


def create_application() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "Production-ready REST API for the Volunteer Information Management System. "
            "Provides authentication, volunteer profile management, opportunity publishing, "
            "and application workflows with full role-based access control."
        ),
        openapi_url=f"{settings.API_V1_PREFIX}/openapi.json" if not settings.ENVIRONMENT == "production" else None,
        docs_url=f"{settings.API_V1_PREFIX}/docs" if settings.ENVIRONMENT != "production" else None,
        redoc_url=f"{settings.API_V1_PREFIX}/redoc" if settings.ENVIRONMENT != "production" else None,
        lifespan=lifespan,
        swagger_ui_parameters={"persistAuthorization": True},
    )

    # ── Middleware ─────────────────────────────────────────────────────────────

    app.add_middleware(GZipMiddleware, minimum_size=1000)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-Process-Time"],
    )

    # ── Request timing / correlation-ID middleware ─────────────────────────────

    @app.middleware("http")
    async def add_process_time_header(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start
        response.headers["X-Process-Time"] = f"{duration:.4f}s"
        return response

    # ── Exception handlers ─────────────────────────────────────────────────────

    @app.exception_handler(VIMSBaseException)
    async def vims_exception_handler(
        request: Request, exc: VIMSBaseException
    ) -> JSONResponse:
        logger.info(
            "Domain exception [%s]: %s — %s %s",
            exc.__class__.__name__,
            exc.detail,
            request.method,
            request.url.path,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.detail},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = []
        for error in exc.errors():
            loc = " -> ".join(str(l) for l in error.get("loc", []) if l != "body")
            errors.append({"field": loc or None, "message": error.get("msg", ""), "code": error.get("type", "")})
        logger.debug("Validation error on %s %s: %s", request.method, request.url.path, errors)
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"error": "Validation failed.", "details": errors},
        )

    @app.exception_handler(IntegrityError)
    async def integrity_error_handler(
        request: Request, exc: IntegrityError
    ) -> JSONResponse:
        logger.warning("DB IntegrityError on %s %s: %s", request.method, request.url.path, str(exc.orig))
        detail = "A resource with conflicting data already exists."
        if exc.orig and "unique" in str(exc.orig).lower():
            detail = "A record with this value already exists."
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"error": detail},
        )

    @app.exception_handler(SQLAlchemyError)
    async def sqlalchemy_error_handler(
        request: Request, exc: SQLAlchemyError
    ) -> JSONResponse:
        logger.error(
            "Unhandled SQLAlchemy error on %s %s: %s",
            request.method,
            request.url.path,
            str(exc),
            exc_info=True,
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"error": "A database error occurred. Please try again later."},
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.error(
            "Unhandled exception on %s %s",
            request.method,
            request.url.path,
            exc_info=True,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "An internal server error occurred."},
        )

    # ── Routes ─────────────────────────────────────────────────────────────────

    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    # ── System endpoints ───────────────────────────────────────────────────────

    @app.get("/health", tags=["System"], summary="Health check")
    async def health_check() -> dict[str, Any]:
        db_healthy = await check_db_connection()
        payload: dict[str, Any] = {
            "status": "healthy" if db_healthy else "degraded",
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
            "database": "ok" if db_healthy else "unreachable",
        }
        return JSONResponse(
            status_code=status.HTTP_200_OK if db_healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
            content=payload,
        )

    @app.get("/", tags=["System"], summary="Root — API info", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "docs": f"{settings.API_V1_PREFIX}/docs",
        }

    return app


# ── Entry point ────────────────────────────────────────────────────────────────

app: FastAPI = create_application()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.ENVIRONMENT == "development",
        log_level="debug" if settings.DEBUG else "info",
    )