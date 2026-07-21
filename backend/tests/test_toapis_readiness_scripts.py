from pathlib import Path

from app.services.toapis_pricing import TOAPIS_PRICING_CONTRACT, ViduPricingAssumptions


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_pricing_contract_has_one_deterministic_source_of_truth() -> None:
    contract = TOAPIS_PRICING_CONTRACT
    assert str(contract.image.price) == "6.3"
    assert contract.image.unit == "IMAGE_REQUEST"
    assert str(contract.video.price) == "20"
    assert contract.video.unit == "VIDEO_SECOND"
    assert contract.estimated_total().to_eng_string() == "172.6"
    assert str(contract.recommended_ceiling) == "190"
    assert contract.snapshot_hash() == contract.snapshot_hash()
    assert isinstance(contract.video.assumptions, ViduPricingAssumptions)
    assert contract.video.assumptions.generation_classification == "STANDARD_GENERATION"
    assert contract.video.assumptions.metadata_generation_type is None


def test_readiness_script_is_read_only_and_only_suggests_paid_command() -> None:
    wrapper = (REPO_ROOT / "scripts" / "toapis-paid-readiness.ps1").read_text(encoding="utf-8")
    helper = (REPO_ROOT / "scripts" / "toapis_paid_readiness.py").read_text(encoding="utf-8")
    combined = wrapper + helper
    for forbidden in (
        "/pricing-review", "/account-balance-review", "/live-enable",
        "/verify-live", "/advance", "/uploads/images", "/images/generations", "/videos/generations",
    ):
        assert forbidden not in combined
    assert "suggestedCommand=" in helper
    assert "THIS COMMAND CREATES PAID REMOTE TASKS." in helper
    assert "subprocess" not in helper


def test_review_script_requires_explicit_acknowledgement() -> None:
    script = (REPO_ROOT / "scripts" / "review-toapis-pricing.ps1").read_text(encoding="utf-8")
    assert "[switch]$AcknowledgePricing" in script
    assert "if (-not $AcknowledgePricing)" in script
    assert "databaseUpdated=false" in script
    assert "/provider-profiles/toapis/pricing-review" in script
    assert "Recommended ceiling: 190" in script


def test_balance_confirmation_and_canary_scripts_keep_paid_execution_explicit() -> None:
    confirmation = (REPO_ROOT / "scripts" / "confirm-toapis-balance.ps1").read_text(encoding="utf-8")
    runner = (REPO_ROOT / "scripts" / "e2e-real-provider.ps1").read_text(encoding="utf-8")
    assert "[switch]$AcknowledgeBalance" in confirmation
    assert "if (-not $AcknowledgeBalance)" in confirmation
    assert "TOKEN_BALANCE_READ_ONLY" in confirmation
    assert "[switch]$CanaryImageOnly" in runner
    assert "[switch]$CanaryVideoFirstLast" in runner
    assert "[switch]$ExecutePaid" in runner
    assert "if (-not $ExecutePaid)" in runner
    assert "MaxBillingUnits must be between 6.3 and 10" in runner
    assert "video tasks: 0" in runner
    assert 'Where-Object { $_.unit -eq "IMAGE_REQUEST" }' in runner
    assert "Video canary MaxBillingUnits must be between 20 and 25" in runner


def test_two_shot_plan_only_and_video_console_review_are_explicit_and_local() -> None:
    runner = (REPO_ROOT / "scripts" / "e2e-real-provider.ps1").read_text(encoding="utf-8")
    planner = (REPO_ROOT / "scripts" / "toapis_two_shot_plan.py").read_text(encoding="utf-8")
    review = (REPO_ROOT / "scripts" / "review-toapis-video-canary.ps1").read_text(encoding="utf-8")
    assert "[switch]$PlanOnly" in runner
    assert "networkCalled=false" in planner
    assert "databaseUpdated=false" in planner
    assert "imageRequests=2" in planner and "videoRequests=2" in planner
    assert "estimatedBillingUnits=172.6" in planner
    assert "videoBillingConsoleReviewed" in planner
    assert "[switch]$AcknowledgeConsoleReview" in review
    assert "if (-not $AcknowledgeConsoleReview)" in review
    assert "databaseUpdated=false" in review


def test_failed_run_recovery_plan_only_is_local_and_precedes_live_execution() -> None:
    runner = (REPO_ROOT / "scripts" / "e2e-real-provider.ps1").read_text(encoding="utf-8")
    planner = (REPO_ROOT / "scripts" / "toapis_recovery_plan.py").read_text(encoding="utf-8")
    assert "[switch]$RecoveryPlanOnly" in runner
    assert "[int]$FailedRunId" in runner
    assert "[int]$RecoverFailedRunId" in runner
    assert "[string]$RecoveryPlanHash" in runner
    assert runner.index("if ($RecoveryPlanOnly)") < runner.index("if (-not $ConfirmLive)")
    assert runner.index("if ($RecoveryPlanOnly)") < runner.index("Invoke-RestMethod")
    assert "RECOVERY_EXECUTION_REQUIRES_EXPLICIT_FUTURE_IMPLEMENTATION" in runner
    for forbidden in ("httpx", "requests", "Invoke-RestMethod", "/live-enable", "/verify-live", "/advance"):
        assert forbidden not in planner
    assert "build_recovery_plan" in planner
    assert "networkCalled" not in planner  # emitted by the pure planning service
    assert "suggestedRecoveryCommand=" in planner
    assert "suggestedRecoveryCommandExecuted=false" in planner
    assert "subprocess" not in planner
