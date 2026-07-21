from __future__ import annotations

from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

import httpx

from app.core.redaction import redact_sensitive
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
from app.providers.models import (
    ImageGenerationRequest,
    ProviderCancelResult,
    ProviderCapabilities,
    ProviderJobResult,
    ProviderResultUrl,
    ProviderSubmitResult,
    RemoteJobStatus,
    VideoGenerationRequest,
    validate_request_capabilities,
)

TOAPIS_BASE_URL = "https://toapis.com/v1"
IMAGE_MODEL = "doubao-seedream-5-0"
VIDEO_MODEL = "viduq3-pro"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_UPLOAD_TYPES = {"image/jpeg", "image/png", "image/webp"}
STATUS_MAP = {
    "queued": RemoteJobStatus.QUEUED,
    "submitted": RemoteJobStatus.QUEUED,
    "in_progress": RemoteJobStatus.RUNNING,
    "processing": RemoteJobStatus.RUNNING,
    "completed": RemoteJobStatus.SUCCEEDED,
    "failed": RemoteJobStatus.FAILED,
}


class ToApisProvider(AsyncGenerationProvider):
    """Dedicated TOAPIS adapter. It has no persistence or workflow responsibilities."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = TOAPIS_BASE_URL,
        timeout_seconds: float = 30,
        client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        allow_live_submit: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._owned_client = client is None
        self._allow_live_submit = allow_live_submit
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
            trust_env=False,
            headers={"User-Agent": "frame-chain-studio-toapis/1"},
        )

    async def aclose(self) -> None:
        if self._owned_client:
            await self._client.aclose()

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_id="toapis",
            display_name="TOAPIS",
            text_to_image=True,
            image_to_image=True,
            image_to_video=True,
            first_last_frame_video=True,
            supports_seed=True,
            supports_cancel=False,
            supports_negative_prompt=False,
            max_reference_images=10,
            max_duration_seconds=16,
            supported_aspect_ratios=["1:1", "4:3", "3:4", "16:9", "9:16", "3:2", "2:3", "21:9", "9:21"],
            supported_output_types=["png", "jpeg", "webp", "mp4"],
        )

    async def submit_image(self, request: ImageGenerationRequest) -> ProviderSubmitResult:
        self._require_live_submit()
        validate_request_capabilities(request, self.get_capabilities())
        prompt = request.prompt
        if request.negative_prompt:
            prompt = f"{prompt}\n\nNegative requirements (must avoid): {request.negative_prompt}"
        payload: dict[str, Any] = {
            "model": IMAGE_MODEL,
            "prompt": prompt,
            "size": request.aspect_ratio or "16:9",
            "n": 1,
            "client_business_id": self._business_id(request.client_request_id),
            "metadata": {"resolution": "2K", "watermark": False},
        }
        image_urls = self._reference_urls(request.metadata)
        if image_urls:
            payload["image_urls"] = image_urls[:10]
        raw = await self._json("POST", "/images/generations", json=payload)
        return self._submit_result(raw, "image", client_request_id=request.client_request_id)

    async def submit_video(self, request: VideoGenerationRequest) -> ProviderSubmitResult:
        self._require_live_submit()
        validate_request_capabilities(request, self.get_capabilities())
        image_urls = []
        if request.start_frame:
            image_urls.append(request.start_frame.url)
        if request.end_frame:
            image_urls.append(request.end_frame.url)
        payload: dict[str, Any] = {
            "model": VIDEO_MODEL,
            "prompt": request.prompt,
            "client_business_id": self._business_id(request.client_request_id),
            "duration": int(request.duration_seconds),
            "resolution": "720p",
            "audio": False,
        }
        if image_urls:
            payload["image_urls"] = image_urls
        elif request.aspect_ratio:
            payload["aspect_ratio"] = request.aspect_ratio
        if request.seed is not None:
            payload["seed"] = request.seed
        raw = await self._json("POST", "/videos/generations", json=payload)
        return self._submit_result(raw, "video", client_request_id=request.client_request_id)

    async def get_job(self, remote_job_id: str) -> ProviderJobResult:
        kind, task_id = self._split_remote_id(remote_job_id)
        raw = await self._json("GET", f"/{kind}s/generations/{quote(task_id, safe='')}")
        status = self._status(raw)
        urls: list[ProviderResultUrl] = []
        if status == RemoteJobStatus.SUCCEEDED:
            item: dict[str, Any]
            if kind == "video" and isinstance(raw.get("video_url"), str):
                item = {"url": raw["video_url"]}
            else:
                result = raw.get("result")
                data = result.get("data") if isinstance(result, dict) else None
                if not isinstance(data, list) or not data or not isinstance(data[0], dict):
                    raise ProviderInvalidResponseError("TOAPIS completed task response is missing its documented result URL.")
                item = data[0]
            url = item.get("url")
            if not isinstance(url, str) or not url:
                raise ProviderInvalidResponseError("TOAPIS completed task response is missing its documented result URL.")
            metadata = {key: item[key] for key in ("format", "last_frame_url") if isinstance(item.get(key), str)}
            if isinstance(raw.get("expires_at"), (str, int)):
                metadata["expires_at"] = str(raw["expires_at"])
            urls.append(ProviderResultUrl(url=url, output_type=kind, metadata=metadata))
        return ProviderJobResult(
            remote_job_id=remote_job_id,
            remote_status=self._raw_status(raw),
            normalized_status=status,
            result_urls=urls,
            error_code=str(raw.get("error", {}).get("code")) if isinstance(raw.get("error"), dict) and raw["error"].get("code") else None,
            error_message="TOAPIS task failed." if status == RemoteJobStatus.FAILED else None,
            raw_response_summary=self._summary(raw),
        )

    async def cancel_job(self, remote_job_id: str) -> ProviderCancelResult:
        del remote_job_id
        raise ProviderCancellationError("TOAPIS remote cancellation has not been verified.")

    async def upload_asset(self, path: Path, *, client_request_id: str) -> ProviderResultUrl:
        self._require_live_submit()
        if path.stat().st_size > MAX_UPLOAD_BYTES:
            raise ProviderInvalidResponseError("TOAPIS image upload exceeds 10 MB.")
        mime = self._mime(path)
        if mime not in ALLOWED_UPLOAD_TYPES:
            raise ProviderInvalidResponseError("TOAPIS production anchors must be JPEG, PNG, or WebP.")
        try:
            with path.open("rb") as handle:
                response = await self._client.post(
                    f"{self.base_url}/uploads/images",
                    headers=self._headers(),
                    files={"file": (f"asset-{client_request_id[-24:]}", handle, mime)},
                    follow_redirects=False,
                )
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError("TOAPIS upload timed out.") from exc
        except httpx.NetworkError as exc:
            raise ProviderNetworkError("TOAPIS upload failed.") from exc
        self._raise_status(response)
        raw = self._decode(response)
        data = raw.get("data")
        if raw.get("success") is not True or not isinstance(data, dict) or not isinstance(data.get("url"), str):
            raise ProviderInvalidResponseError("TOAPIS upload response is invalid.")
        return ProviderResultUrl(
            url=data["url"], mime_type=data.get("mime_type") if isinstance(data.get("mime_type"), str) else mime,
            output_type="url", metadata={"upload_id": data.get("id"), "size": data.get("size")},
        )

    async def _json(self, method: str, path: str, *, json: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = await self._client.request(method, f"{self.base_url}{path}", headers=self._headers(), json=json, follow_redirects=False)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError("TOAPIS request timed out.") from exc
        except httpx.NetworkError as exc:
            raise ProviderNetworkError("TOAPIS network request failed.") from exc
        self._raise_status(response)
        return self._decode(response)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    def _require_live_submit(self) -> None:
        if not self._allow_live_submit:
            from app.providers.exceptions import ProviderConfigurationError
            raise ProviderConfigurationError("LIVE_ORCHESTRATION_DISABLED")

    def _decode(self, response: httpx.Response) -> dict[str, Any]:
        try:
            raw = response.json()
        except ValueError as exc:
            raise ProviderInvalidResponseError("TOAPIS returned malformed JSON.") from exc
        if not isinstance(raw, dict):
            raise ProviderInvalidResponseError("TOAPIS returned a non-object response.")
        return raw

    def _raise_status(self, response: httpx.Response) -> None:
        status = response.status_code
        if status < 400:
            return
        details = {"status_code": status, "body": self._summary(self._decode(response)) if response.content else ""}
        if status == 401:
            raise ProviderAuthenticationError("TOAPIS authentication failed.", http_status=status, details=details)
        if status in {402, 403, 400, 422}:
            raise ProviderInvalidResponseError("TOAPIS rejected the request.", http_status=status, details=details)
        if status == 404:
            raise ProviderJobNotFoundError("TOAPIS task or model was not found.", http_status=status, details=details)
        if status == 429:
            raise ProviderRateLimitError("TOAPIS rate limit exceeded.", http_status=status, details=details)
        if status in {500, 502, 503, 504}:
            raise ProviderRemoteServerError("TOAPIS service is unavailable.", http_status=status, details=details)
        raise ProviderInvalidResponseError("TOAPIS request failed.", http_status=status, details=details)

    def _submit_result(
        self, raw: dict[str, Any], kind: Literal["image", "video"], *, client_request_id: str | None = None,
    ) -> ProviderSubmitResult:
        data: dict[str, Any] = raw["data"] if isinstance(raw.get("data"), dict) else raw
        task_id = data.get("task_id") or data.get("taskId") or data.get("id")
        result = raw.get("result")
        items = result.get("data") if isinstance(result, dict) else None
        urls = [
            ProviderResultUrl(url=item["url"], output_type=kind)
            for item in items or []
            if isinstance(item, dict) and isinstance(item.get("url"), str) and item["url"]
        ] if isinstance(items, list) else []
        if kind == "video" and not urls and isinstance(raw.get("video_url"), str) and raw["video_url"]:
            urls = [ProviderResultUrl(url=raw["video_url"], output_type="video")]
        if urls:
            return ProviderSubmitResult(
                remote_status=RemoteJobStatus.SUCCEEDED,
                response_mode="INLINE_RESULT",
                result_urls=urls,
                client_request_id=client_request_id,
                raw_response_summary=self._summary(raw),
            )
        if not isinstance(task_id, str) or not task_id:
            raise ProviderInvalidResponseError("TOAPIS submit response is missing a task ID and result URL.")
        raw_status = self._raw_status(raw)
        status = STATUS_MAP.get(raw_status.lower(), RemoteJobStatus.QUEUED) if isinstance(raw_status, str) else RemoteJobStatus.QUEUED
        return ProviderSubmitResult(
            remote_job_id=f"{kind}:{task_id}", remote_status=status,
            client_request_id=client_request_id, raw_response_summary=self._summary(raw),
        )

    def _status(self, raw: dict[str, Any]) -> RemoteJobStatus:
        value = self._raw_status(raw)
        normalized = STATUS_MAP.get(value.lower()) if isinstance(value, str) else None
        if normalized is None:
            raise ProviderInvalidResponseError("TOAPIS returned an unknown task status.")
        return normalized

    def _raw_status(self, raw: dict[str, Any]) -> str | None:
        data = raw.get("data")
        value = (data.get("status") if isinstance(data, dict) else None) or raw.get("status")
        return value if isinstance(value, str) else None

    def _split_remote_id(self, value: str) -> tuple[Literal["image", "video"], str]:
        kind, separator, task_id = value.partition(":")
        if separator and kind in {"image", "video"} and task_id:
            return kind, task_id  # type: ignore[return-value]
        raise ProviderInvalidResponseError("TOAPIS remote task ID has no task type discriminator.")

    def _business_id(self, value: str | None) -> str:
        safe = "".join(char for char in (value or "") if char.isascii() and (char.isalnum() or char in "-_"))
        return (safe or "fcs-request")[:96]

    def _reference_urls(self, metadata: dict[str, Any]) -> list[str]:
        value = metadata.get("reference_urls")
        return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []

    def _summary(self, raw: dict[str, Any]) -> str:
        import json
        import re
        value = json.dumps(redact_sensitive(raw), ensure_ascii=True)
        value = re.sub(r"(?i)Bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer ***REDACTED***", value)
        if self._api_key:
            value = value.replace(self._api_key, "***REDACTED***")
        return value[:2000]

    def _mime(self, path: Path) -> str:
        head = path.read_bytes()[:12]
        if head.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if head.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
            return "image/webp"
        return "application/octet-stream"
