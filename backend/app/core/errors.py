import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Business error rendered as {"error": {"code", "message", "details"}}."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def error_body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def _validation_details(exc: RequestValidationError) -> dict[str, Any]:
    # Drop "input"/"ctx": they would echo submitted values such as passwords back to the client and into logs.
    fields = [
        {"loc": list(err.get("loc", [])), "msg": err.get("msg", ""), "type": err.get("type", "")}
        for err in exc.errors()
    ]
    return {"fields": fields}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(error_body(exc.code, exc.message, exc.details), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            error_body("VALIDATION_ERROR", "Invalid request data.", _validation_details(exc)),
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "HTTP_ERROR")
        return JSONResponse(error_body(code, str(exc.detail)), status_code=exc.status_code)

    from botocore.exceptions import BotoCoreError, ClientError
    from sqlalchemy.exc import OperationalError

    @app.exception_handler(OperationalError)
    async def _database_down(_: Request, exc: OperationalError) -> JSONResponse:
        # Connection lost / database unreachable: a clear temporary error, nothing internal in the answer.
        logger.error("database unavailable: %s", type(exc.orig).__name__ if exc.orig else type(exc).__name__)
        return JSONResponse(
            error_body("SERVICE_UNAVAILABLE", "The service is temporarily unavailable. Try again shortly."),
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            headers={"Retry-After": "30"},
        )

    @app.exception_handler(BotoCoreError)
    @app.exception_handler(ClientError)
    async def _storage_down(_: Request, exc: Exception) -> JSONResponse:
        logger.error("file storage unavailable: %s", type(exc).__name__)
        return JSONResponse(
            error_body("STORAGE_UNAVAILABLE", "File storage is temporarily unavailable. Try again shortly."),
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            headers={"Retry-After": "30"},
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error")
        return JSONResponse(
            error_body("INTERNAL_ERROR", "Unexpected server error."),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
