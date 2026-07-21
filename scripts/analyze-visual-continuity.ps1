param(
    [int]$VideoAssetId,
    [int]$ProjectId,
    [int]$ShotId,
    [int]$StartAnchorAssetId,
    [int]$TargetKeyframeAssetId,
    [int]$TailFrameAssetId,
    [ValidateSet("visual-continuity-v1")][string]$AnalysisVersion = "visual-continuity-v1",
    [switch]$WriteReport,
    [switch]$GenerateContactSheet,
    [switch]$Run6Calibration
)

$ErrorActionPreference = "Stop"
$helper = Join-Path $PSScriptRoot "analyze_visual_continuity.py"
$arguments = @($helper, "--analysis-version", $AnalysisVersion)
if ($Run6Calibration) { $arguments += "--run6-calibration" }
if ($VideoAssetId -gt 0) { $arguments += @("--video-asset-id", [string]$VideoAssetId) }
if ($ProjectId -gt 0) { $arguments += @("--project-id", [string]$ProjectId) }
if ($ShotId -gt 0) { $arguments += @("--shot-id", [string]$ShotId) }
if ($StartAnchorAssetId -gt 0) { $arguments += @("--start-anchor-asset-id", [string]$StartAnchorAssetId) }
if ($TargetKeyframeAssetId -gt 0) { $arguments += @("--target-keyframe-asset-id", [string]$TargetKeyframeAssetId) }
if ($TailFrameAssetId -gt 0) { $arguments += @("--tail-frame-asset-id", [string]$TailFrameAssetId) }
if ($WriteReport) { $arguments += "--write-report" }
if ($GenerateContactSheet) { $arguments += "--generate-contact-sheet" }
& python @arguments
if ($LASTEXITCODE -ne 0) { throw "VISUAL_CONTINUITY_ANALYSIS_FAILED" }
