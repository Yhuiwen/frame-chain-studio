from typing import Any
from urllib.parse import quote

import httpx

from app.providers.async_base import AsyncGenerationProvider
from app.providers.exceptions import (
    ProviderAuthenticationError,
    ProviderCancellationError,
    ProviderInvalidResponseError,
    ProviderJobNotFoundError,
    ProviderNetworkError,
    ProviderRateLimitError,
    ProviderRemoteServerError,
    ProviderTimeoutError,
)
from app.providers.mapping import (
    apply_request_mapping,
    extract_result_urls,
    get_by_path,
    normalize_remote_status,
    require_by_path,
    summarize_response,
)
from app.providers.models import (
    ImageGenerationRequest,
    MappedHttpProviderConfig,
    ProviderCancelResult,
    ProviderCapabilities,
    ProviderJobResult,
    ProviderSubmitResult,
    RemoteJobStatus,
    ResponseMappingConfig,
    VideoGenerationRequest,
    validate_request_capabilities,
)

MAX_ERROR_BODY_CHARS = 2000


class MappedAsyncHttpProvider(AsyncGenerationProvider):
    def __init__(
        self,
        config: MappedHttpProviderConfig,
        *,
        client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.config = config
        self._owned_client = client is None
        self._extra_headers = extra_headers or {}
        timeout = httpx.Timeout(config.request_timeout_seconds)
        self._client = client or httpx.AsyncClient(
            timeout=timeout,
            verify=config.verify_tls,
            transport=transport,
            headers={"User-Agent": "frame-chain-studio-provider/0.1"},
        )

    async def __aenter__(self) -> "MappedAsyncHttpProvider":
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owned_client:
            await self._client.aclose()

    def get_capabilities(self) -> ProviderCapabilities:
        return self.config.capabilities

    async def submit_image(self, request: ImageGenerationRequest) -> ProviderSubmitResult:
        validate_request_capabilities(request, self.config.capabilities)
        payload = apply_request_mapping(
            request.model_dump(mode="json"),
            self.config.mapping.image_request.fields,
            self.config.mapping.image_request.fixed_fields,
            skip_none=self.config.mapping.image_request.skip_none,
        )
        raw = await self._request_json("POST", self.config.image_submit_path, json_payload=payload)
        return self._parse_submit(raw, self.config.mapping.submit_response)

    async def submit_video(self, request: VideoGenerationRequest) -> ProviderSubmitResult:
        validate_request_capabilities(request, self.config.capabilities)
        payload = apply_request_mapping(
            request.model_dump(mode="json"),
            self.config.mapping.video_request.fields,
            self.config.mapping.video_request.fixed_fields,
            skip_none=self.config.mapping.video_request.skip_none,
        )
        raw = await self._request_json("POST", self.config.video_submit_path, json_payload=payload)
        return self._parse_submit(raw, self.config.mapping.submit_response)

    async def get_job(self, remote_job_id: str) -> ProviderJobResult:
        path = self._path_from_template(self.config.job_status_path_template, remote_job_id)
        raw = await self._request_json("GET", path)
        return self._parse_job(raw, self.config.mapping.job_response, remote_job_id)

    async def cancel_job(self, remote_job_id: str) -> ProviderCancelResult:
        path = self._path_from_template(self.config.job_cancel_path_template, remote_job_id)
        raw = await self._request_json("POST", path)
        mapping = self.config.mapping.cancel_response or self.config.mapping.job_response
        status_value = require_by_path(raw, mapping.status_path)
        return ProviderCancelResult(
            remote_job_id=remote_job_id,
            accepted=normalize_remote_status(status_value, mapping) == RemoteJobStatus.CANCELLED,
            remote_status=normalize_remote_status(status_value, mapping),
            message=str(status_value),
            raw_response_summary=summarize_response(raw),
        )

    def _build_url(self, path: str) -> str:
        return f"{self.config.base_url.rstrip('/')}/{path.lstrip('/')}"

    def _path_from_template(self, template: str, remote_job_id: str) -> str:
        encoded = quote(remote_job_id, safe="")
        return template.replace("{remote_job_id}", encoded)

    def _headers(self) -> dict[str, str]:
        headers = dict(self._extra_headers)
        if self.config.api_key:
            headers[self.config.auth_header_name] = (
                f"{self.config.auth_prefix}{self.config.api_key.get_secret_value()}"
            )
        return headers

    async def _request_json(self, method: str, path: str, *, json_payload: dict[str, Any] | None = None) -> Any:
        try:
            response = await self._client.request(
                method,
                self._build_url(path),
                json=json_payload,
                headers=self._headers(),
                follow_redirects=False,
            )
        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as exc:
            raise ProviderTimeoutError("Provider request timed out.", details={"error": str(exc)}) from exc
        except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.NetworkError) as exc:
            raise ProviderNetworkError("Provider network request failed.", details={"error": str(exc)}) from exc
        if response.status_code >= 400:
            self._raise_for_status(response)
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderInvalidResponseError(
                "Provider returned non-JSON response.",
                http_status=response.status_code,
                details={"body": response.text[:MAX_ERROR_BODY_CHARS]},
            ) from exc

    def _raise_for_status(self, response: httpx.Response) -> None:
        details = {"status_code": response.status_code, "body": self._safe_error_body(response)}
        status = response.status_code
        if status in {401, 403}:
            raise ProviderAuthenticationError("Provider authentication failed.", http_status=status, details=details)
        if status == 404:
            raise ProviderJobNotFoundError("Provider job was not found.", http_status=status, details=details)
        if status == 405:
            raise ProviderCancellationError("Provider cancellation is not supported.", http_status=status, details=details)
        if status == 429:
            raise ProviderRateLimitError("Provider rate limit exceeded.", http_status=status, details=details)
        if status in {500, 502, 503, 504}:
            raise ProviderRemoteServerError("Provider remote server error.", http_status=status, details=details)
        raise ProviderInvalidResponseError("Provider request was rejected.", http_status=status, details=details)

    def _safe_error_body(self, response: httpx.Response) -> str:
        try:
            return summarize_response(response.json(), max_chars=MAX_ERROR_BODY_CHARS)
        except ValueError:
            return response.text[:MAX_ERROR_BODY_CHARS]

    def _parse_submit(self, raw: Any, mapping: ResponseMappingConfig) -> ProviderSubmitResult:
        remote_job_id = require_by_path(raw, mapping.remote_job_id_path)
        status_value = require_by_path(raw, mapping.status_path)
        if not isinstance(remote_job_id, str) or not remote_job_id:
            raise ProviderInvalidResponseError("Provider submit response did not include a valid job ID.")
        return ProviderSubmitResult(
            remote_job_id=remote_job_id,
            remote_status=normalize_remote_status(status_value, mapping),
            accepted=True,
            raw_response_summary=summarize_response(raw),
        )

    def _parse_job(self, raw: Any, mapping: ResponseMappingConfig, remote_job_id: str) -> ProviderJobResult:
        status_value = require_by_path(raw, mapping.status_path)
        progress_value = None
        if mapping.progress_path:
            progress_value = require_by_path(raw, mapping.progress_path)
        if progress_value is not None and not isinstance(progress_value, int | float):
            raise ProviderInvalidResponseError("Provider progress value is not numeric.")
        error_code = None
        if mapping.error_code_path:
            value = get_by_path(raw, mapping.error_code_path, None)
            error_code = str(value) if value is not None else None
        error_message = None
        if mapping.error_message_path:
            value = get_by_path(raw, mapping.error_message_path, None)
            error_message = str(value) if value is not None else None
        return ProviderJobResult(
            remote_job_id=remote_job_id,
            remote_status=status_value if isinstance(status_value, str | int) else str(status_value),
            normalized_status=normalize_remote_status(status_value, mapping),
            progress=float(progress_value) if progress_value is not None else None,
            result_urls=extract_result_urls(raw, mapping),
            error_code=error_code,
            error_message=error_message,
            raw_response_summary=summarize_response(raw),
        )
