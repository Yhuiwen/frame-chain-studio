from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict


class SeedreamPricingAssumptions(BaseModel):
    model_config = ConfigDict(frozen=True)

    resolution: Literal["2K"] = "2K"
    images_per_request: Literal[1] = 1
    request_count: Literal[2] = 2


class ViduPricingAssumptions(BaseModel):
    model_config = ConfigDict(frozen=True)

    resolution: Literal["720p"] = "720p"
    audio: Literal[False] = False
    duration_seconds_per_request: Literal[4] = 4
    request_count: Literal[2] = 2
    billed_video_seconds_total: Literal[8] = 8
    ordered_image_url_count: Literal[2] = 2
    metadata_generation_type: None = None
    generation_classification: Literal["STANDARD_GENERATION"] = "STANDARD_GENERATION"


class ToApisModelPricingContract(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_key: str
    remote_model: str
    price: Decimal
    unit: str
    source_reference: str
    assumptions: SeedreamPricingAssumptions | ViduPricingAssumptions


class ToApisPricingContract(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: str
    billing_unit: Literal["TOAPIS_CREDIT"]
    source_kind: Literal["OFFICIAL_PUBLIC_MODEL_GUIDE"]
    contract_reference: str
    image: ToApisModelPricingContract
    video: ToApisModelPricingContract
    recommended_ceiling: Decimal

    def canonical_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"recommended_ceiling"})

    def snapshot_hash(self) -> str:
        encoded = json.dumps(self.canonical_payload(), sort_keys=True, separators=(",", ":")).encode()
        return sha256(encoded).hexdigest()

    def assumptions_json(self, *, image: bool) -> str:
        assumptions = self.image.assumptions if image else self.video.assumptions
        return json.dumps(assumptions.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))

    def estimated_total(self) -> Decimal:
        return self.image.price * Decimal(2) + self.video.price * Decimal(8)


TOAPIS_PRICING_CONTRACT = ToApisPricingContract(
    version="toapis-public-2026-07-21",
    billing_unit="TOAPIS_CREDIT",
    source_kind="OFFICIAL_PUBLIC_MODEL_GUIDE",
    contract_reference="TOAPIS_OFFICIAL_PUBLIC_GUIDES_2026-07-21",
    image=ToApisModelPricingContract(
        model_key="toapis-seedream-5",
        remote_model="doubao-seedream-5-0",
        price=Decimal("6.3"),
        unit="IMAGE_REQUEST",
        source_reference="https://toapis.com/en/pricing#doubao-seedream-5-0",
        assumptions=SeedreamPricingAssumptions(),
    ),
    video=ToApisModelPricingContract(
        model_key="toapis-viduq3-pro",
        remote_model="viduq3-pro",
        price=Decimal("20"),
        unit="VIDEO_SECOND",
        source_reference="https://docs.toapis.com/docs/en/api-reference/videos/viduq3/generation",
        assumptions=ViduPricingAssumptions(),
    ),
    recommended_ceiling=Decimal("190"),
)
