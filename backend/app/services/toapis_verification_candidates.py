from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.core.errors import AppError


class ToApisVerificationCandidateKey(StrEnum):
    SHORT_CONTINUITY_CANARY = "SHORT_CONTINUITY_CANARY"
    LEGACY_FULL_TWO_SHOT = "LEGACY_FULL_TWO_SHOT"


@dataclass(frozen=True, slots=True)
class ToApisVerificationCandidate:
    key: ToApisVerificationCandidateKey
    image_task_limit: int
    video_task_limit: int
    video_duration_seconds_each: int
    max_attempts_per_task: int
    automatic_retry_allowed: bool
    recommended_billing_ceiling: Decimal
    requires_initial_anchor: bool
    plan_only_allowed: bool
    verification_mode: str
    paid_execution_entry_implemented: bool

    @property
    def total_video_seconds(self) -> int:
        return self.video_task_limit * self.video_duration_seconds_each

    def estimated_billing(
        self, *, image_price: Decimal, video_price_per_second: Decimal
    ) -> Decimal:
        return (
            image_price * self.image_task_limit + video_price_per_second * self.total_video_seconds
        )


SHORT_CONTINUITY_CANARY = ToApisVerificationCandidate(
    key=ToApisVerificationCandidateKey.SHORT_CONTINUITY_CANARY,
    image_task_limit=2,
    video_task_limit=2,
    video_duration_seconds_each=2,
    max_attempts_per_task=1,
    automatic_retry_allowed=False,
    recommended_billing_ceiling=Decimal("110"),
    requires_initial_anchor=False,
    plan_only_allowed=True,
    verification_mode="VISUAL_EXPERIMENT_SHORT",
    paid_execution_entry_implemented=False,
)

LEGACY_FULL_TWO_SHOT = ToApisVerificationCandidate(
    key=ToApisVerificationCandidateKey.LEGACY_FULL_TWO_SHOT,
    image_task_limit=2,
    video_task_limit=2,
    video_duration_seconds_each=4,
    max_attempts_per_task=1,
    automatic_retry_allowed=False,
    recommended_billing_ceiling=Decimal("190"),
    requires_initial_anchor=True,
    plan_only_allowed=True,
    verification_mode="LEGACY_PAID_TWO_SHOT",
    paid_execution_entry_implemented=True,
)

_CANDIDATES = {item.key.value: item for item in (SHORT_CONTINUITY_CANARY, LEGACY_FULL_TWO_SHOT)}


def resolve_toapis_verification_candidate(value: str) -> ToApisVerificationCandidate:
    try:
        return _CANDIDATES[value]
    except KeyError as exc:
        raise AppError(
            "TOAPIS_VERIFICATION_CANDIDATE_INVALID", "Unknown TOAPIS verification candidate.", 422
        ) from exc
