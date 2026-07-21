param(
    [Parameter(Mandatory=$true)][int]$ProjectId,
    [Parameter(Mandatory=$true)][int]$SourceRunId,
    [Parameter(Mandatory=$true)][ValidateSet("SHORT_CONTINUITY_CANARY","FULL_CONTINUITY_RETEST")][string]$Candidate,
    [Parameter(Mandatory=$true)][switch]$PlanOnly,
    [int]$SelectedBaselineAssetId,
    [switch]$SaveDraft
)
$arguments=@("scripts/prepare_visual_experiment_authorization.py","--project-id",$ProjectId,"--source-run-id",$SourceRunId,"--candidate",$Candidate,"--plan-only")
if($PSBoundParameters.ContainsKey("SelectedBaselineAssetId")){$arguments += @("--selected-baseline-asset-id",$SelectedBaselineAssetId)}
if($SaveDraft){$arguments += "--save-draft"}
& python @arguments
exit $LASTEXITCODE
