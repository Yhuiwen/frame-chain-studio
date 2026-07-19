import json
from typing import Any

from app.models.entities import GenerationKind, GenerationRequest, GenerationTask, GenerationTaskType
from app.providers.exceptions import ProviderUnsupportedCapabilityError
from app.providers.models import (
    AssetReference,
    ImageGenerationRequest,
    ProviderCapabilities,
    VideoGenerationRequest,
    validate_request_capabilities,
)


class ProviderRequestFactory:
    def build(
        self,
        generation_request: GenerationRequest,
        task: GenerationTask,
        capabilities: ProviderCapabilities,
        prepared_assets: dict[int, AssetReference] | None = None,
    ) -> ImageGenerationRequest | VideoGenerationRequest:
        payload = self._payload(task)
        prompt = str(payload.get("prompt") or generation_request.prompt_snapshot or "")
        negative_prompt = str(payload.get("negative_prompt") or generation_request.negative_prompt_snapshot or "")
        if task.task_type == GenerationTaskType.KEYFRAME_GENERATION or generation_request.kind == GenerationKind.KEYFRAME:
            request = ImageGenerationRequest(
                provider_id=task.provider_id,
                model=str(payload.get("model") or ""),
                prompt=prompt,
                negative_prompt=negative_prompt or None,
                width=int(payload.get("width") or 1024),
                height=int(payload.get("height") or 576),
                aspect_ratio=payload.get("aspect_ratio") if isinstance(payload.get("aspect_ratio"), str) else "16:9",
                seed=payload.get("seed") if isinstance(payload.get("seed"), int) else None,
                reference_asset_ids=self._int_list(payload.get("reference_asset_ids")),
                metadata=self._dict(payload.get("metadata")),
                client_request_id=task.idempotency_key,
            )
            validate_request_capabilities(request, capabilities)
            return request
        video_request = VideoGenerationRequest(
            provider_id=task.provider_id,
            model=str(payload.get("model") or ""),
            prompt=prompt,
            negative_prompt=negative_prompt or None,
            duration_seconds=float(payload.get("duration_seconds") or 4),
            fps=float(payload.get("fps") or 24),
            aspect_ratio=payload.get("aspect_ratio") if isinstance(payload.get("aspect_ratio"), str) else "16:9",
            seed=payload.get("seed") if isinstance(payload.get("seed"), int) else None,
            start_frame=self._asset_ref(self._int_list(payload.get("input_asset_ids"))[0], task.provider_id, prepared_assets)
            if self._int_list(payload.get("input_asset_ids"))
            else None,
            end_frame=self._asset_ref(self._int_list(payload.get("input_asset_ids"))[1], task.provider_id, prepared_assets)
            if payload.get("generation_mode") == "FIRST_LAST_FRAME" and len(self._int_list(payload.get("input_asset_ids"))) > 1
            else None,
            metadata=self._dict(payload.get("metadata")),
            client_request_id=task.idempotency_key,
        )
        validate_request_capabilities(video_request, capabilities)
        return video_request

    def _payload(self, task: GenerationTask) -> dict[str, Any]:
        try:
            parsed = json.loads(task.request_payload_json or "{}")
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _dict(self, value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def _int_list(self, value: Any) -> list[int]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, int)]

    def _asset_ref(
        self,
        asset_id: int,
        provider_id: str | None = None,
        prepared_assets: dict[int, AssetReference] | None = None,
    ) -> AssetReference:
        if prepared_assets and asset_id in prepared_assets:
            return prepared_assets[asset_id]
        if provider_id and provider_id != "mock":
            raise ProviderUnsupportedCapabilityError(
                "PROVIDER_ASSET_UPLOAD_UNSUPPORTED: remote providers require an upload-capable asset preparer."
            )
        return AssetReference(asset_id=asset_id, url=f"asset://{asset_id}")
