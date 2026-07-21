param(
 [Parameter(Mandatory=$true)][int]$ProjectId,[Parameter(Mandatory=$true)][ValidateSet("SHORT_CONTINUITY_CANARY")][string]$Candidate,
 [Parameter(Mandatory=$true)][int]$SelectedBaselineAssetId,[Parameter(Mandatory=$true)][string]$ExpectedRegenerationPlanHash,
 [Parameter(Mandatory=$true)][string]$ExpectedBaselineHash,[Parameter(Mandatory=$true)][string]$ExpectedExperimentPlanHash,
 [switch]$AcknowledgePlanReview,[switch]$AcknowledgeRun6Failures,[switch]$AcknowledgePromptContract,[switch]$AcknowledgeMotionDelta,
 [switch]$AcknowledgeTaskLimits,[switch]$AcknowledgeEstimatedBilling,[switch]$AcknowledgeNoPaidExecution,[string]$Comment=""
)
$a=@("scripts/review_visual_experiment_plan.py","--project-id",$ProjectId,"--candidate",$Candidate,"--selected-baseline-asset-id",$SelectedBaselineAssetId,"--expected-regeneration-plan-hash",$ExpectedRegenerationPlanHash,"--expected-baseline-hash",$ExpectedBaselineHash,"--expected-experiment-plan-hash",$ExpectedExperimentPlanHash,"--comment",$Comment)
foreach($p in @("AcknowledgePlanReview","AcknowledgeRun6Failures","AcknowledgePromptContract","AcknowledgeMotionDelta","AcknowledgeTaskLimits","AcknowledgeEstimatedBilling","AcknowledgeNoPaidExecution")){if($PSBoundParameters.ContainsKey($p)){$a += "--$($p -creplace '([A-Z])','-$1' -replace '^-','' | ForEach-Object {$_.ToLower()})"}}
& python @a
exit $LASTEXITCODE
