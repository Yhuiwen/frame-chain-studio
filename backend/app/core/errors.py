import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_id import REQUEST_ID_HEADER

logger = logging.getLogger("frame_chain_studio.errors")


class AppError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def error_payload(code: str, message: str, request_id: str | None = None) -> dict[str, dict[str, str]]:
    payload = {"error": {"code": code, "message": message}}
    if request_id:
        payload["error"]["request_id"] = request_id
    return payload


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _headers(request_id: str | None) -> dict[str, str] | None:
    return {REQUEST_ID_HEADER: request_id} if request_id else None


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        request_id = _request_id(request)
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(exc.code, exc.message, request_id),
            headers=_headers(request_id),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        request_id = _request_id(request)
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload("HTTP_ERROR", str(exc.detail), request_id),
            headers=_headers(request_id),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        request_id = _request_id(request)
        return JSONResponse(
            status_code=422,
            content=error_payload("VALIDATION_ERROR", str(exc.errors()), request_id),
            headers=_headers(request_id),
        )

    @app.exception_handler(Exception)
    async def internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = _request_id(request)
        logger.exception("Unhandled request error request_id=%s", request_id, exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=error_payload("INTERNAL_SERVER_ERROR", "Internal server error.", request_id),
            headers=_headers(request_id),
        )
