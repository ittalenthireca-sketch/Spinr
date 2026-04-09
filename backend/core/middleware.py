from fastapi.middleware.cors import CORSMiddleware
from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from loguru import logger
from core.config import settings
from utils.rate_limiter import default_limiter, rate_limit_exceeded_handler

# Explicit allowed HTTP methods and headers — never use wildcard "*" in production
_ALLOWED_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
_ALLOWED_HEADERS = [
    "Authorization",
    "Content-Type",
    "Accept",
    "X-Request-ID",
    "X-Requested-With",
]


def init_middleware(app):
    """Initialize all middleware components."""

    # -----------------------------------------------------------------------
    # Build CORS origin list
    # -----------------------------------------------------------------------
    # Start with any origins set via the ALLOWED_ORIGINS env var
    origins = [
        origin.strip()
        for origin in settings.ALLOWED_ORIGINS.split(",")
        if origin.strip()
    ]

    # always_allowed: localhost is development-only — never present in production
    if settings.ENV == 'production':
        always_allowed = [
            "https://spinr-admin.vercel.app",
        ]
    else:
        always_allowed = [
            "https://spinr-admin.vercel.app",
            "http://localhost:3000",
            "http://localhost:3001",
        ]

    origins.extend(always_allowed)
    origins = list(set(o for o in origins if o))  # deduplicate, remove empty strings

    # -----------------------------------------------------------------------
    # Production guard — wildcard CORS is never acceptable in production
    # -----------------------------------------------------------------------
    if settings.ENV == 'production' and "*" in origins:
        raise RuntimeError(
            "FATAL: CORS wildcard '*' is not permitted in production. "
            "Set ALLOWED_ORIGINS env var to a comma-separated list of specific "
            "origins (e.g. 'https://spinr.app,https://admin.spinr.app')."
        )

    if settings.ENV != 'production' and "*" in origins:
        logger.warning(
            "CORS: wildcard '*' is enabled. Acceptable in development "
            "but will be blocked in production."
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=_ALLOWED_METHODS,
        allow_headers=_ALLOWED_HEADERS,
    )

    # -----------------------------------------------------------------------
    # Exception handler — ensures CORS headers are present on all error responses
    # (FastAPI does not attach CORS headers to unhandled exceptions by default)
    # -----------------------------------------------------------------------
    @app.exception_handler(Exception)
    async def cors_exception_handler(request: Request, exc: Exception):
        origin = request.headers.get("origin")

        if hasattr(exc, 'status_code') and hasattr(exc, 'detail'):
            response = JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail}
            )
        else:
            logger.error(f"Unhandled exception: {exc}")
            response = JSONResponse(
                status_code=500,
                content={"detail": "Internal Server Error"}
            )

        # Add CORS headers only for origins in the explicit allowlist
        if origin and (origin in origins or "*" in origins):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Methods"] = ", ".join(_ALLOWED_METHODS)
            response.headers["Access-Control-Allow-Headers"] = ", ".join(_ALLOWED_HEADERS)

        return response

    # -----------------------------------------------------------------------
    # Rate Limiting Middleware
    # -----------------------------------------------------------------------
    app.state.limiter = default_limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

    logger.info(
        f"Middleware initialized — CORS origins: {origins} | "
        f"Methods: {_ALLOWED_METHODS}"
    )
