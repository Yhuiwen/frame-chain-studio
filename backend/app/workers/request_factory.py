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
            reference_ids = self._bounded_reference_ids(
                self._int_list(payload.get("reference_asset_ids")), capabilities.max_reference_images
            )
            image_metadata = self._metadata_with_reference_downgrade(
                self._dict(payload.get("metadata")),
                requested_reference_count=len(self._int_list(payload.get("reference_asset_ids"))),
                used_reference_count=len(reference_ids),
                reference_limit=capabilities.max_reference_images,
                reserved_reference_count=0,
            )
            if prepared_assets:
                image_metadata = {
                    **image_metadata,
                    "reference_urls": [prepared_assets[item].url for item in reference_ids if item in prepared_assets],
                }
            request = ImageGenerationRequest(
                provider_id=task.provider_id,
                model=str(payload.get("model") or ""),
                prompt=prompt,
                negative_prompt=negative_prompt or None,
                width=int(payload.get("width") or 1024),
                height=int(payload.get("height") or 576),
                aspect_ratio=payload.get("aspect_ratio") if isinstance(payload.get("aspect_ratio"), str) else "16:9",
                seed=payload.get("seed") if isinstance(payload.get("seed"), int) else None,
                reference_asset_ids=reference_ids,
                metadata=image_metadata,
                client_request_id=task.idempotency_key,
            )
            validate_request_capabilities(request, capabilities)
            return request
        input_asset_ids = self._int_list(payload.get("input_asset_ids"))
        start_frame = self._asset_ref(input_asset_ids[0], task.provider_id, prepared_assets) if input_asset_ids else None
        end_frame = (
            self._asset_ref(input_asset_ids[1], task.provider_id, prepared_assets)
            if payload.get("generation_mode") == "FIRST_LAST_FRAME" and len(input_asset_ids) > 1
            else None
        )
        reserved_reference_count = int(start_frame is not None) + int(end_frame is not None)
        requested_reference_ids = self._int_list(payload.get("reference_asset_ids"))
        available_reference_capacity = (
            0 if task.provider_id == "toapis" else max(capabilities.max_reference_images - reserved_reference_count, 0)
        )
        reference_asset_ids = self._bounded_reference_ids(
            requested_reference_ids,
            available_reference_capacity,
        )
        video_request = VideoGenerationRequest(
            provider_id=task.provider_id,
            model=str(payload.get("model") or ""),
            prompt=prompt,
            negative_prompt=negative_prompt or None,
            duration_seconds=float(payload.get("duration_seconds") or 4),
            fps=float(payload.get("fps") or 24),
            aspect_ratio=payload.get("aspect_ratio") if isinstance(payload.get("aspect_ratio"), str) else "16:9",
            seed=payload.get("seed") if isinstance(payload.get("seed"), int) else None,
            start_frame=start_frame,
            end_frame=end_frame,
            reference_assets=[
                self._asset_ref(asset_id, task.provider_id, prepared_assets)
                for asset_id in reference_asset_ids
            ],
            metadata=self._metadata_with_reference_downgrade(
                self._dict(payload.get("metadata")),
                requested_reference_count=len(requested_reference_ids),
                used_reference_count=len(reference_asset_ids),
                reference_limit=available_reference_capacity,
                reserved_reference_count=reserved_reference_count,
            ),
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

    def _bounded_reference_ids(self, asset_ids: list[int], limit: int) -> list[int]:
        if limit <= 0:
            return []
        return asset_ids[:limit]

    def _metadata_with_reference_downgrade(
        self,
        metadata: dict[str, Any],
        *,
        requested_reference_count: int,
        used_reference_count: int,
        reference_limit: int,
        reserved_reference_count: int,
    ) -> dict[str, Any]:
        dropped_reference_count = max(requested_reference_count - used_reference_count, 0)
        if dropped_reference_count == 0:
            return metadata
        downgraded = {
            **metadata,
            "reference_asset_ids_truncated": True,
            "requested_reference_asset_count": requested_reference_count,
            "used_reference_asset_count": used_reference_count,
            "dropped_reference_asset_count": dropped_reference_count,
            "reference_asset_limit": reference_limit,
            "reserved_reference_asset_count": reserved_reference_count,
        }
        if reference_limit == 0 and reserved_reference_count:
            downgraded["structured_references_dropped_for_anchor_capacity"] = True
        return downgraded

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
