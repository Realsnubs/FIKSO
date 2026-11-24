import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import api_router
from app.core.config import get_settings
from app.core.errors import error_body, register_error_handlers
from app.core.logging import configure_logging, request_id_var
from app.schemas.common import ErrorResponse

access_logger = logging.getLogger("fikso.access")
_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{8,64}")
_HSTS = "max-age=31536000; includeSubDomains"
# One photo/document (10 MB) plus multipart overhead.
MAX_REQUEST_BYTES = 12 * 1024 * 1024
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(self), camera=(), microphone=()",
}


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    docs = settings.docs_enabled
    app = FastAPI(
        title="FIKSO API",
        version="0.1.0",
        openapi_url="/api/v1/openapi.json" if docs else None,
        docs_url="/api/v1/docs" if docs else None,
        redoc_url=None,
        responses={
            400: {"model": ErrorResponse},
            401: {"model": ErrorResponse},
            403: {"model": ErrorResponse},
        },
    )
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
        )

    allowed_origins = {o.rstrip("/") for o in [*settings.cors_origins, settings.app_origin or ""] if o}

    @app.middleware("http")
    async def request_id(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        incoming = request.headers.get("X-Request-ID", "")
        # Only a safe-looking ID is reused (it ends up in logs); anything else gets a fresh one.
        rid = incoming[:64] if _REQUEST_ID.fullmatch(incoming[:64]) else uuid.uuid4().hex
        token = request_id_var.set(rid)
        started = time.perf_counter()
        try:
            origin = request.headers.get("origin")
            # CSRF defence in depth: the refresh cookie is SameSite=Lax; cookie-authenticated auth endpoints
            # additionally refuse a cross-site Origin.
            length = request.headers.get("content-length", "")
            if length.isdigit() and int(length) > MAX_REQUEST_BYTES:
                # Refused before the body is read or spooled; nginx enforces the same for chunked bodies.
                response: Response = JSONResponse(
                    error_body("REQUEST_TOO_LARGE", "The request is too large."), status_code=413
                )
            elif (
                request.method == "POST"
                and request.url.path.startswith("/api/v1/auth/")
                and origin
                and allowed_origins
                and origin.rstrip("/") not in allowed_origins
            ):
                response = JSONResponse(
                    error_body("FORBIDDEN_ORIGIN", "Request origin not allowed."), status_code=403
                )
            else:
                response = await call_next(request)
            response.headers["X-Request-ID"] = rid
            for header, value in _SECURITY_HEADERS.items():
                response.headers.setdefault(header, value)
            if settings.environment in ("production", "staging"):
                response.headers.setdefault("Strict-Transport-Security", _HSTS)
            route = request.scope.get("route")
            # Route template, never the concrete URL or query string (IDs/tokens stay out of the logs).
            access_logger.info(
                "%s %s %s %.0fms",
                request.method,
                getattr(route, "path", "unmatched"),
                response.status_code,
                (time.perf_counter() - started) * 1000,
            )
        finally:
            request_id_var.reset(token)
        return response

    register_error_handlers(app)
    app.include_router(api_router)
    return app


app = create_app()
