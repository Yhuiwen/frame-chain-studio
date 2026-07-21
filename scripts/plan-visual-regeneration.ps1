param(
    [int]$ProjectId = 22,
    [int]$SourceRunId = 6,
    [Parameter(Mandatory = $true)][string]$Strategy,
    [switch]$PlanOnly,
    [decimal]$MaxBillingUnits = 190,
    [string]$PricingSnapshotHash = "",
    [switch]$SaveDraft
)

if (-not $PlanOnly) { throw "PLAN_ONLY_REQUIRED" }
$arguments = @(
    ".\scripts\plan_visual_regeneration.py", "--project-id", $ProjectId,
    "--source-run-id", $SourceRunId, "--strategy", $Strategy,
    "--max-billing-units", $MaxBillingUnits, "--plan-only"
)
if ($PricingSnapshotHash) { $arguments += @("--pricing-snapshot-hash", $PricingSnapshotHash) }
if ($SaveDraft) { $arguments += "--save-draft" }
python @arguments
if ($LASTEXITCODE -ne 0) { throw "VISUAL_REGENERATION_PLAN_FAILED" }
