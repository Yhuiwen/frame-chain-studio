param(
 [Parameter(Mandatory=$true)][int]$ProjectId,
 [Parameter(Mandatory=$true)][ValidateSet(83,89)][int]$SelectedBaselineAssetId,
 [Parameter(Mandatory=$true)][string]$ExpectedSourceReviewStatus,
 [Parameter(Mandatory=$true)][string]$ExpectedBaselineDraftHash,
 [switch]$AcknowledgeBaselineReview,[switch]$AcknowledgeThreeDimensionalToyStyle,[switch]$AcknowledgeCharacterConsistency,
 [switch]$AcknowledgeCameraAndEnvironment,[switch]$AcknowledgeNoTextLogoWatermark,[string]$Comment=""
)
$a=@("scripts/review_project_visual_baseline.py","--project-id",$ProjectId,"--selected-baseline-asset-id",$SelectedBaselineAssetId,"--expected-source-review-status",$ExpectedSourceReviewStatus,"--expected-baseline-draft-hash",$ExpectedBaselineDraftHash,"--comment",$Comment)
foreach($p in @("AcknowledgeBaselineReview","AcknowledgeThreeDimensionalToyStyle","AcknowledgeCharacterConsistency","AcknowledgeCameraAndEnvironment","AcknowledgeNoTextLogoWatermark")){if($PSBoundParameters.ContainsKey($p)){$a += "--$($p -creplace '([A-Z])','-$1' -replace '^-','' | ForEach-Object {$_.ToLower()})"}}
& python @a
exit $LASTEXITCODE
