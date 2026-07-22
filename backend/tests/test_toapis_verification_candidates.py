from decimal import Decimal

import pytest

from app.core.errors import AppError
from app.services.toapis_verification_candidates import (
    LEGACY_FULL_TWO_SHOT,
    SHORT_CONTINUITY_CANARY,
    resolve_toapis_verification_candidate,
)


def test_short_candidate_is_explicit_and_frozen() -> None:
    value = resolve_toapis_verification_candidate("SHORT_CONTINUITY_CANARY")
    assert value is SHORT_CONTINUITY_CANARY
    assert (value.image_task_limit, value.video_task_limit) == (2, 2)
    assert value.video_duration_seconds_each == 2
    assert value.total_video_seconds == 4
    assert value.max_attempts_per_task == 1
    assert value.automatic_retry_allowed is False
    assert value.recommended_billing_ceiling == Decimal("110")


def test_unknown_candidate_is_rejected() -> None:
    with pytest.raises(AppError, match="Unknown TOAPIS verification candidate"):
        resolve_toapis_verification_candidate("UNKNOWN")


def test_candidate_cost_uses_exact_decimal_prices() -> None:
    result = SHORT_CONTINUITY_CANARY.estimated_billing(
        image_price=Decimal("6.3"), video_price_per_second=Decimal("20")
    )
    assert result == Decimal("92.6")
    assert isinstance(result, Decimal)
    assert SHORT_CONTINUITY_CANARY.estimated_billing(
        image_price=Decimal("7.1"), video_price_per_second=Decimal("21")
    ) == Decimal("98.2")


def test_legacy_full_contract_is_isolated_and_preserved() -> None:
    assert LEGACY_FULL_TWO_SHOT.video_duration_seconds_each == 4
    assert LEGACY_FULL_TWO_SHOT.total_video_seconds == 8
    assert LEGACY_FULL_TWO_SHOT.recommended_billing_ceiling == Decimal("190")
    assert LEGACY_FULL_TWO_SHOT.estimated_billing(
        image_price=Decimal("6.3"), video_price_per_second=Decimal("20")
    ) == Decimal("172.6")
    assert LEGACY_FULL_TWO_SHOT is not SHORT_CONTINUITY_CANARY
