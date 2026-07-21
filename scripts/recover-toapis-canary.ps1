param(
    [Parameter(Mandatory = $true)][int]$RunId,
    [Parameter(Mandatory = $true)][ValidatePattern("^tsk_img_[A-Za-z0-9]+$")][string]$ExistingRemoteTaskId,
    [string]$ExistingResultUrl,
    [switch]$AcknowledgeExistingTaskRecovery,
    [ValidateRange(2, 300)][int]$PollIntervalSeconds = 10,
    [ValidateRange(1, 120)][int]$TimeoutMinutes = 20,
    [string]$ApiBaseUrl = "http://127.0.0.1:8000/api"
)

$ErrorActionPreference = "Stop"
if (-not $AcknowledgeExistingTaskRecovery) {
    Write-Host "EXISTING_TASK_RECOVERY_ACKNOWLEDGEMENT_REQUIRED"
    Write-Host "networkCalled=false"
    Write-Host "newImageSubmits=0"
    exit 0
}
if ([string]::IsNullOrWhiteSpace($ExistingResultUrl)) {
    $helper = Join-Path $PSScriptRoot "recover_toapis_existing_task.py"
    $readOnly = & python $helper --existing-remote-task-id $ExistingRemoteTaskId
    if ($LASTEXITCODE -ne 0) { throw "EXISTING_REMOTE_TASK_QUERY_FAILED" }
    $ExistingResultUrl = ($readOnly | ConvertFrom-Json).result_url
}
if (-not $ExistingResultUrl.StartsWith("https://")) { throw "EXISTING_RESULT_URL_INVALID" }

$api = $ApiBaseUrl.TrimEnd('/')
$body = @{
    existing_remote_task_id = $ExistingRemoteTaskId
    existing_result_url = $ExistingResultUrl
    acknowledge_existing_task_recovery = $true
} | ConvertTo-Json
$prepared = Invoke-RestMethod -Method Post -Uri "$api/provider-verification-runs/$RunId/recover-existing-canary-result" -ContentType "application/json" -Body $body -TimeoutSec 15
$deadline = (Get-Date).AddMinutes($TimeoutMinutes)
while ((Get-Date) -lt $deadline) {
    $state = Invoke-RestMethod -Method Get -Uri "$api/provider-verification-runs/$RunId" -TimeoutSec 10
    if ($state.status -in @("PASSED", "FAILED_BUT_BILLED")) { break }
    $progress = Invoke-RestMethod -Method Post -Uri "$api/provider-verification-runs/$RunId/advance" -TimeoutSec 15
    if ($progress.status -in @("PASSED", "FAILED_BUT_BILLED")) { break }
    Start-Sleep -Seconds $PollIntervalSeconds
}
$state = Invoke-RestMethod -Method Get -Uri "$api/provider-verification-runs/$RunId" -TimeoutSec 10
Write-Host "runId=$RunId"
Write-Host "status=$($state.status)"
Write-Host "historicalImageSubmits=1"
Write-Host "newImageSubmits=0"
Write-Host "videoSubmits=0"
Write-Host "uploads=0"
if ($state.status -notin @("PASSED", "FAILED_BUT_BILLED")) { throw "CANARY_RECOVERY_$($state.status)" }
