param(
  [int]$BackendPort = 8000,
  [int]$FrontendPort = 5173,
  [int]$FakeProviderPort = 8090,
  [switch]$SkipWorkerRestart
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$BackendRoot = Join-Path $ProjectRoot "backend"
$FrontendRoot = Join-Path $ProjectRoot "frontend"
$RunId = "e2e-{0}-{1}" -f (Get-Date -Format "yyyyMMdd-HHmmss"), ([guid]::NewGuid().ToString("N").Substring(0, 8))
$RunRoot = Join-Path $ProjectRoot ".run\e2e\$RunId"
$LogRoot = Join-Path $RunRoot "logs"
$PidFile = Join-Path $RunRoot "processes.json"
$StorageDir = Join-Path $RunRoot "storage"
$BackupDir = Join-Path $RunRoot "backups"
$DatabasePath = Join-Path $RunRoot "frame-chain-e2e.db"
$DatabaseUrl = "sqlite:///" + ($DatabasePath -replace "\\", "/")
$ProviderConfig = Join-Path $RunRoot "provider-config.e2e.json"
$BaseUrl = "http://127.0.0.1:$BackendPort/api"
$FakeBaseUrl = "http://127.0.0.1:$FakeProviderPort/fake/v1"
$ProcessItems = @()
$OriginalError = $null
$ProviderUsageEvidence = [ordered]@{}
$Summary = [ordered]@{
  run_root = ".run/e2e/$RunId"
  database = "isolated-temp-sqlite"
  storage = "isolated-temp-storage"
  project_id = $null
  shot_ids = @()
  shots = @()
  worker_restart = [ordered]@{ skipped = [bool]$SkipWorkerRestart }
  script_storyboard = $null
  structured_continuity = $null
  provider_usage = $null
  provider_requests = @()
  range = @()
  render = $null
  ffprobe = $null
  backup_restore = $null
}

function Fail($Stage, $Message) {
  throw "[$Stage] $Message"
}

function Require-Command($Name) {
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
    Fail "preflight" "$Name is required but was not found on PATH."
  }
}

function Test-PortFree($Port, $Name) {
  $busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  if ($busy) { Fail "preflight" "$Name port $Port is already in use." }
}

function Quote-Ps($Value) {
  return "'" + ([string]$Value -replace "'", "''") + "'"
}

function Get-CommonEnv($WorkerId = $null, $ResultWorkerId = $null) {
  $envItems = @(
    "`$env:FCS_DATABASE_URL=$(Quote-Ps $DatabaseUrl)",
    "`$env:FCS_STORAGE_DIR=$(Quote-Ps $StorageDir)",
    "`$env:FCS_FIXTURE_DIR=$(Quote-Ps (Join-Path $BackendRoot "tests\fixtures"))",
    "`$env:FCS_PROVIDER_CONFIG_FILE=$(Quote-Ps $ProviderConfig)",
    "`$env:FCS_LOG_DIR=$(Quote-Ps $LogRoot)",
    "`$env:FCS_ENV='development'",
    "`$env:FCS_RESULT_ALLOWED_PRIVATE_HOSTS='127.0.0.1'",
    "`$env:FCS_DEFAULT_IMAGE_PROVIDER_ID='fake-http'",
    "`$env:FCS_DEFAULT_VIDEO_PROVIDER_ID='fake-http'",
    "`$env:FCS_BACKEND_PORT='$BackendPort'",
    "`$env:FCS_FRONTEND_PORT='$FrontendPort'",
    "`$env:FCS_FAKE_PROVIDER_PORT='$FakeProviderPort'"
  )
  if ($WorkerId) { $envItems += "`$env:FCS_WORKER_ID=$(Quote-Ps $WorkerId)" }
  if ($ResultWorkerId) { $envItems += "`$env:FCS_RESULT_WORKER_ID=$(Quote-Ps $ResultWorkerId)" }
  return $envItems -join "; "
}

function Save-PidFile {
  @($ProcessItems) | ConvertTo-Json -Depth 5 | Set-Content -Path $PidFile -Encoding UTF8
}

function Get-ProcessTreeIds($RootPid) {
  $children = @(Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $RootPid })
  foreach ($child in $children) {
    Get-ProcessTreeIds $child.ProcessId
    $child.ProcessId
  }
}

function Stop-ServiceItem($Item) {
  $ids = @($Item.pid) + @(Get-ProcessTreeIds $Item.pid)
  foreach ($id in @($ids | Select-Object -Unique | Sort-Object -Descending)) {
    $process = Get-Process -Id $id -ErrorAction SilentlyContinue
    if ($process) {
      Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
      try {
        Wait-Process -Id $id -Timeout 10 -ErrorAction SilentlyContinue
      } catch {}
    }
  }
}

function Stop-TrackedServices {
  foreach ($item in @($ProcessItems | Sort-Object pid -Descending)) {
    Stop-ServiceItem $item
  }
}

function Start-ServiceProcess($Name, $WorkingDirectory, $Command) {
  New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null
  $stdout = Join-Path $LogRoot "$Name.out.log"
  $stderr = Join-Path $LogRoot "$Name.err.log"
  $process = Start-Process -FilePath "powershell" -WindowStyle Hidden -PassThru -WorkingDirectory $WorkingDirectory `
    -RedirectStandardOutput $stdout -RedirectStandardError $stderr `
    -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $Command)
  $item = [ordered]@{ name = $Name; pid = $process.Id; stdout = $stdout; stderr = $stderr }
  $script:ProcessItems += $item
  Save-PidFile
  return $item
}

function Assert-ServiceAlive($Name) {
  $item = @($ProcessItems | Where-Object { $_.name -eq $Name } | Select-Object -Last 1)[0]
  if (-not $item) { Fail "process" "Service '$Name' was not started." }
  if (-not (Get-Process -Id $item.pid -ErrorAction SilentlyContinue)) {
    $tail = ""
    if (Test-Path $item.stderr) { $tail = (Get-Content $item.stderr -Tail 80) -join "`n" }
    Fail "process" "Service '$Name' exited early. stderr tail:`n$tail"
  }
}

function Wait-FileUnlocked($Path, [int]$TimeoutSeconds = 20) {
  if (-not (Test-Path $Path)) { return }
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  do {
    try {
      $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
      $stream.Close()
      return
    } catch {
      Start-Sleep -Milliseconds 250
    }
  } while ((Get-Date) -lt $deadline)
  Fail "restore" "Timed out waiting for database file to be released: $Path"
}

function Stop-TrackedService($Name) {
  $matches = @($ProcessItems | Where-Object { $_.name -eq $Name })
  if ($matches.Count -eq 0) { Fail "process" "Tracked service '$Name' was not found." }
  foreach ($item in $matches) { Stop-ServiceItem $item }
  $script:ProcessItems = @($ProcessItems | Where-Object { $_.name -ne $Name })
  Save-PidFile
}

function Invoke-Api($Method, $Path, $Body = $null, $Headers = $null) {
  $parameters = @{
    Method = $Method
    Uri = "$BaseUrl$Path"
    TimeoutSec = 30
  }
  if ($Headers) { $parameters.Headers = $Headers }
  if ($null -ne $Body) {
    $parameters.ContentType = "application/json"
    $parameters.Body = ($Body | ConvertTo-Json -Depth 12)
  }
  return Invoke-RestMethod @parameters
}

function Get-StringSha256($Value) {
  $sha = [System.Security.Cryptography.SHA256]::Create()
  try {
    $bytes = [System.Text.Encoding]::UTF8.GetBytes([string]$Value)
    return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
  } finally {
    $sha.Dispose()
  }
}

function Upload-ProjectImage($ProjectId, $Name) {
  $imagePath = Join-Path $RunRoot "$Name.png"
  $env:FCS_E2E_IMAGE_PATH = $imagePath
  $env:FCS_E2E_IMAGE_NAME = $Name
  Push-Location $BackendRoot
  try {
    @'
import os
from PIL import Image

name = os.environ["FCS_E2E_IMAGE_NAME"]
color = "red" if "character" in name else "blue"
Image.new("RGB", (16, 16), color).save(os.environ["FCS_E2E_IMAGE_PATH"], format="PNG")
'@ | python -
  } finally {
    Pop-Location
    Remove-Item Env:FCS_E2E_IMAGE_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:FCS_E2E_IMAGE_NAME -ErrorAction SilentlyContinue
  }
  $output = & curl.exe -sS --max-time 20 -X POST -F "file=@$imagePath;type=image/png;filename=$Name.png" "http://127.0.0.1:$BackendPort/api/projects/$ProjectId/assets/images"
  if ($LASTEXITCODE -ne 0) { Fail "upload" "Project image upload failed for $Name." }
  return ($output | ConvertFrom-Json)
}

function Wait-Http($Name, $Url, [int]$TimeoutSeconds = 60) {
  for ($i = 0; $i -lt ($TimeoutSeconds * 2); $i++) {
    try {
      Invoke-WebRequest $Url -UseBasicParsing -TimeoutSec 2 | Out-Null
      return
    } catch {
      Assert-ServiceAlive $Name
      Start-Sleep -Milliseconds 500
    }
  }
  Fail "ready" "$Name did not become ready at $Url"
}

function Wait-BackendReady {
  for ($i = 0; $i -lt 120; $i++) {
    try {
      $ready = Invoke-Api "GET" "/ready"
      if ($ready.status -eq "ready") { return $ready }
    } catch {
      Assert-ServiceAlive "backend"
      Start-Sleep -Milliseconds 500
    }
  }
  Fail "ready" "Backend did not report ready."
}

function Wait-WorkersReady {
  for ($i = 0; $i -lt 120; $i++) {
    try {
      $workers = Invoke-Api "GET" "/workers/status"
      if ($workers.generation.online_count -ge 1 -and $workers.result.online_count -ge 1 -and $workers.render.online_count -ge 1) {
        return $workers
      }
    } catch {}
    foreach ($name in @("generation-worker", "result-worker", "render-worker")) { Assert-ServiceAlive $name }
    Start-Sleep -Milliseconds 500
  }
  Fail "workers" "Generation, result, and render workers did not all become online."
}

function Start-Stack {
  Start-ServiceProcess "fake-provider" $BackendRoot "$(Get-CommonEnv); python -m uvicorn fake_provider.app:app --host 127.0.0.1 --port $FakeProviderPort" | Out-Null
  Wait-Http "fake-provider" "http://127.0.0.1:$FakeProviderPort/fake/v1/ready"
  Start-ServiceProcess "backend" $BackendRoot "$(Get-CommonEnv); python -m uvicorn app.main:app --host 127.0.0.1 --port $BackendPort" | Out-Null
  Wait-BackendReady | Out-Null
  Start-ServiceProcess "generation-worker" $BackendRoot "$(Get-CommonEnv 'e2e-generation-worker'); python -m app.workers.cli" | Out-Null
  Start-ServiceProcess "result-worker" $BackendRoot "$(Get-CommonEnv $null 'e2e-result-worker'); python -m app.workers.result_cli" | Out-Null
  Start-ServiceProcess "render-worker" $BackendRoot "$(Get-CommonEnv 'e2e-render-worker'); python -m app.workers.render_cli" | Out-Null
  Wait-WorkersReady | Out-Null
  Start-ServiceProcess "frontend" $FrontendRoot "`$env:VITE_API_BASE_URL=''; `$env:VITE_API_PROXY_TARGET='http://127.0.0.1:$BackendPort'; npm.cmd run dev -- --host 127.0.0.1 --port $FrontendPort" | Out-Null
  Wait-Http "frontend" "http://127.0.0.1:$FrontendPort"
}

function Restart-Stack {
  Stop-TrackedServices
  $script:ProcessItems = @()
  Save-PidFile
  Start-Stack
}

function Start-RestartedGenerationWorker {
  Start-ServiceProcess "generation-worker" $BackendRoot "$(Get-CommonEnv 'e2e-generation-worker-restarted'); python -m app.workers.cli" | Out-Null
  for ($i = 0; $i -lt 120; $i++) {
    try {
      $workers = Invoke-Api "GET" "/workers/status"
      $restarted = @($workers.generation.workers | Where-Object { $_.worker_id -eq "e2e-generation-worker-restarted" -and $_.online -eq $true })
      if ($restarted.Count -ge 1) { return }
    } catch {}
    Assert-ServiceAlive "generation-worker"
    Start-Sleep -Milliseconds 500
  }
  Fail "worker-restart" "Restarted GenerationWorker did not become visible."
}

function Get-Detail($ProjectId) {
  return Invoke-Api "GET" "/projects/$ProjectId"
}

function Get-TaskForRequest($Detail, $RequestId) {
  return @($Detail.tasks | Where-Object { $_.generation_request_id -eq $RequestId } | Sort-Object id -Descending | Select-Object -First 1)[0]
}

function Get-RequestById($Detail, $RequestId) {
  return @($Detail.requests | Where-Object { $_.id -eq $RequestId })[0]
}

function Wait-TaskStatus($ProjectId, $RequestId, [string[]]$Statuses, [int]$TimeoutSeconds = 120) {
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  do {
    $detail = Get-Detail $ProjectId
    $task = Get-TaskForRequest $detail $RequestId
    if ($task -and ($Statuses -contains [string]$task.status)) {
      return @($detail, $task)
    }
    Start-Sleep -Milliseconds 500
  } while ((Get-Date) -lt $deadline)
  $lastStatus = if ($task) { $task.status } else { "missing" }
  Fail "task:$RequestId" "Timed out waiting for task status $($Statuses -join ','); last status=$lastStatus."
}

function Wait-ShotStatus($ProjectId, $ShotId, [string]$Status, [int]$TimeoutSeconds = 120) {
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  do {
    $detail = Get-Detail $ProjectId
    $shot = @($detail.shots | Where-Object { $_.id -eq $ShotId })[0]
    if ($shot -and [string]$shot.status -eq $Status) {
      return @($detail, $shot)
    }
    Start-Sleep -Milliseconds 500
  } while ((Get-Date) -lt $deadline)
  $lastStatus = if ($shot) { $shot.status } else { "missing" }
  Fail "shot:$ShotId" "Timed out waiting for shot status $Status; last status=$lastStatus."
}

function Wait-RenderStatus($RenderId, [string[]]$Statuses, [int]$TimeoutSeconds = 180) {
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  do {
    $render = Invoke-Api "GET" "/renders/$RenderId"
    if ($Statuses -contains [string]$render.status) { return $render }
    Start-Sleep -Milliseconds 500
  } while ((Get-Date) -lt $deadline)
  Fail "render:$RenderId" "Timed out waiting for render status $($Statuses -join ','); last status=$($render.status)."
}

function Download-Media($Url, $Name) {
  $target = Join-Path $RunRoot "$Name.bin"
  & curl.exe -sS --max-time 30 -o $target "http://127.0.0.1:$BackendPort$Url"
  if ($LASTEXITCODE -ne 0) { Fail "media" "curl download failed for $Url." }
  if (-not (Test-Path $target)) { Fail "media" "Download target was not created for $Url." }
  return $target
}

function Assert-MediaRange($Url, $ExpectedSize, $Name) {
  $fullPath = Download-Media $Url $Name
  $actualSize = (Get-Item $fullPath).Length
  if ($ExpectedSize -and $actualSize -ne [int64]$ExpectedSize) {
    Fail "range" "Full download size mismatch for $Url; expected $ExpectedSize, got $actualSize."
  }
  $rangePath = Join-Path $RunRoot "$Name.range.bin"
  $headerPath = Join-Path $RunRoot "$Name.range.headers.txt"
  & curl.exe -sS --max-time 10 -D $headerPath -o $rangePath -r 0-15 "http://127.0.0.1:$BackendPort$Url"
  if ($LASTEXITCODE -ne 0) { Fail "range" "curl range request failed for $Url." }
  $headerText = Get-Content $headerPath -Raw
  if ($headerText -notmatch "HTTP/\S+\s+206") { Fail "range" "Expected 206 for $Url; headers: $headerText" }
  if ($headerText -notmatch "(?i)accept-ranges:\s*bytes") { Fail "range" "Missing Accept-Ranges for $Url; headers: $headerText" }
  if ($headerText -notmatch "(?i)content-range:\s*bytes 0-15/$actualSize") { Fail "range" "Missing Content-Range for $Url; headers: $headerText" }
  if ((Get-Item $rangePath).Length -ne 16) { Fail "range" "Range response length is not 16 for $Url." }
  $fullBytes = [System.IO.File]::ReadAllBytes($fullPath)[0..15]
  $rangeBytes = [System.IO.File]::ReadAllBytes($rangePath)
  for ($i = 0; $i -lt 16; $i++) {
    if ($fullBytes[$i] -ne $rangeBytes[$i]) { Fail "range" "Range bytes do not match full download for $Url." }
  }
  $Summary.range += [ordered]@{ name = $Name; url = $Url; size = $actualSize; status = 206 }
  return $fullPath
}

function Get-AssetById($Detail, $AssetId) {
  return @($Detail.assets | Where-Object { $_.id -eq $AssetId })[0]
}

function Get-FakeStats {
  return Invoke-RestMethod -Method GET -Uri "$FakeBaseUrl/test/stats" -TimeoutSec 5
}

function Configure-ProviderCostLedger($ProjectId) {
  Write-Host "==> Provider profile and cost ledger setup"
  $profile = Invoke-Api "POST" "/provider-profiles" @{
    name = "E2E Fake HTTP"
    provider_key = "fake-http"
    adapter_type = "FAKE"
    display_name = "Fake HTTP Provider"
    base_url = "http://127.0.0.1:$FakeProviderPort"
    enabled = $true
    config = @{}
  }
  $imageModel = Invoke-Api "POST" "/provider-profiles/$($profile.id)/models" @{
    model_key = "fake-image"
    display_name = "Fake Image"
    generation_type = "IMAGE"
    enabled = $true
    capabilities = @{ supported_aspect_ratios = @("16:9") }
    limits = @{ max_reference_images = 2 }
    pricing = @{ rules = @(@{ unit = "REQUEST"; price = "0" }, @{ unit = "INPUT_IMAGE"; price = "0" }) }
    currency = "USD"
  }
  $videoModel = Invoke-Api "POST" "/provider-profiles/$($profile.id)/models" @{
    model_key = "fake-video"
    display_name = "Fake Video"
    generation_type = "VIDEO"
    enabled = $true
    capabilities = @{ first_last_frame_video = $true; supported_aspect_ratios = @("16:9") }
    limits = @{ max_duration_seconds = 12 }
    pricing = @{ rules = @(@{ unit = "REQUEST"; price = "0" }, @{ unit = "VIDEO_SECOND"; price = "0" }, @{ unit = "INPUT_IMAGE"; price = "0" }) }
    currency = "USD"
  }
  $validation = Invoke-Api "POST" "/provider-profiles/$($profile.id)/validate"
  if ($validation.configuration_valid -ne $true) { Fail "provider-profile" "Fake ProviderProfile did not validate." }
  $contract = Invoke-Api "POST" "/provider-profiles/$($profile.id)/verify-contract"
  if ($contract.status -ne "PASSED") { Fail "provider-profile" "Fake ProviderProfile contract verification did not pass." }
  $live = Invoke-Api "POST" "/provider-profiles/$($profile.id)/verify-live" @{ confirm_live = $false; max_cost = $null }
  if ($live.error_code -ne "BLOCKED_LIVE_VERIFICATION") { Fail "provider-profile" "Live verification was not blocked by default." }
  Invoke-Api "PATCH" "/projects/$ProjectId" @{
    image_provider_id = "fake-http"
    video_provider_id = "fake-http"
    image_model = "fake-image"
    video_model = "fake-video"
    default_aspect_ratio = "16:9"
    default_video_duration_seconds = 1.0
    default_seed = 7
  } | Out-Null
  $script:ProviderUsageEvidence = [ordered]@{
    provider_profile_id = $profile.id
    image_model_profile_id = $imageModel.id
    video_model_profile_id = $videoModel.id
    validation_valid = $validation.configuration_valid
    contract_status = $contract.status
    live_verification_error_code = $live.error_code
  }
}

function Assert-UsageCostLedger($ProjectId) {
  Write-Host "==> Usage, budget, and CSV verification"
  $summary = Invoke-Api "GET" "/projects/$ProjectId/usage/summary"
  $records = @((Invoke-Api "GET" "/projects/$ProjectId/usage/records") | ForEach-Object { $_ })
  $currencies = @($summary.currencies)
  $requestEstimateCount = @($records | Where-Object { $_.record_type -eq "ESTIMATE" -and -not $_.generation_task_id }).Count
  $taskEstimateCount = @($records | Where-Object { $_.record_type -eq "ESTIMATE" -and $_.generation_task_id }).Count
  $actualCount = @($records | Where-Object { $_.record_type -eq "PROVIDER_REPORTED" }).Count
  if ($summary.unknown_cost_count -ne 0) { Fail "usage" "Fake Provider usage should not produce UNKNOWN costs." }
  if ($currencies.Count -lt 1 -or [string]$currencies[0].estimated_total -ne "0" -or [string]$currencies[0].actual_total -ne "0") {
    Fail "usage" "Fake Provider totals must remain explicit zero, not missing or unknown."
  }
  if ($requestEstimateCount -ne $summary.request_count) { Fail "usage" "Request-level estimates do not match request count." }
  if ($taskEstimateCount -lt $requestEstimateCount -or $actualCount -lt $requestEstimateCount) { Fail "usage" "Task estimate or actual usage records are missing." }

  $budget = Invoke-Api "PUT" "/projects/$ProjectId/budget" @{
    currency = "USD"
    warning_limit = "0.01"
    hard_limit = "0.01"
    per_request_limit = "0.01"
    period_type = "PROJECT_TOTAL"
    unknown_cost_policy = "BLOCK"
    enabled = $true
  }
  if ($budget.enabled -ne $true -or $budget.unknown_cost_policy -ne "BLOCK") { Fail "usage" "Budget policy was not persisted." }

  $csvUrl = "$BaseUrl/projects/$ProjectId/usage/export.csv"
  $csvText = Invoke-WebRequest -Uri $csvUrl -UseBasicParsing -TimeoutSec 20
  if ($csvText.Content -notmatch "estimated_cost" -or $csvText.Content -notmatch "FAKE_PROVIDER") {
    Fail "usage" "Usage CSV did not include expected headers and fake cost source."
  }

  $script:ProviderUsageEvidence["request_count"] = $summary.request_count
  $script:ProviderUsageEvidence["usage_record_count"] = $records.Count
  $script:ProviderUsageEvidence["request_estimate_count"] = $requestEstimateCount
  $script:ProviderUsageEvidence["task_estimate_count"] = $taskEstimateCount
  $script:ProviderUsageEvidence["actual_count"] = $actualCount
  $script:ProviderUsageEvidence["unknown_cost_count"] = $summary.unknown_cost_count
  $script:ProviderUsageEvidence["estimated_total"] = [string]$currencies[0].estimated_total
  $script:ProviderUsageEvidence["actual_total"] = [string]$currencies[0].actual_total
  $script:ProviderUsageEvidence["budget_enabled"] = $budget.enabled
  $script:ProviderUsageEvidence["budget_unknown_cost_policy"] = $budget.unknown_cost_policy
  $script:ProviderUsageEvidence["csv_verified"] = $true
}

function Assert-ProviderVideoRequest($VideoRequest, $ShotNumber) {
  $stats = Get-FakeStats
  $task = @((Get-Detail $Summary.project_id).tasks | Where-Object { $_.generation_request_id -eq $VideoRequest.id } | Sort-Object id -Descending | Select-Object -First 1)[0]
  $submission = @($stats.submissions | Where-Object { $_.job_id -eq $task.remote_job_id })[0]
  if (-not $submission) { Fail "provider-request" "No Fake Provider submission found for video request $($VideoRequest.id)." }
  $body = $submission.body
  if (-not $body.client_request_id) { Fail "provider-request" "Video request $($VideoRequest.id) is missing client_request_id." }
  if (-not $body.input.first_frame_url) { Fail "provider-request" "Video request $($VideoRequest.id) is missing input.first_frame_url." }
  if ($ShotNumber -gt 1 -and -not $body.input.last_frame_url) {
    Fail "provider-request" "First-last-frame request $($VideoRequest.id) is missing input.last_frame_url."
  }
  $Summary.provider_requests += [ordered]@{
    request_id = $VideoRequest.id
    task_id = $task.id
    shot_number = $ShotNumber
    remote_job_id = $task.remote_job_id
    client_request_id = $body.client_request_id
    first_frame_url = $body.input.first_frame_url
    last_frame_url = $body.input.last_frame_url
  }
}

function Assert-ProviderKeyframeRequest($RequestId, $ExpectedText) {
  $detail = Get-Detail $Summary.project_id
  $task = Get-TaskForRequest $detail $RequestId
  $stats = Get-FakeStats
  $submission = @($stats.submissions | Where-Object { $_.job_id -eq $task.remote_job_id })[0]
  if (-not $submission) { Fail "provider-request" "No Fake Provider submission found for keyframe request $RequestId." }
  if ([string]$submission.body.input.text -notmatch [regex]::Escape($ExpectedText)) {
    Fail "provider-request" "Keyframe provider request did not use the expected structured snapshot."
  }
}

function Configure-StructuredShot($ProjectId, $ShotId) {
  Write-Host "==> Structured continuity library"
  $characterRef = Upload-ProjectImage $ProjectId "character-reference"
  $locationRef = Upload-ProjectImage $ProjectId "location-reference"
  $character = Invoke-Api "POST" "/projects/$ProjectId/characters" @{
    name = "Mira"
    appearance = "white coat"
    default_clothing = "white coat"
    continuity_notes = "keep the coat bright"
  }
  Invoke-Api "POST" "/characters/$($character.id)/references" @{
    asset_id = $characterRef.id
    reference_type = "FULL_BODY"
    is_primary = $true
    sort_order = 1
  } | Out-Null
  $location = Invoke-Api "POST" "/projects/$ProjectId/locations" @{
    name = "Harbor Gate"
    description = "misty dock"
    lighting = "green sodium lamps"
    time_of_day = "night"
  }
  Invoke-Api "POST" "/locations/$($location.id)/references" @{
    asset_id = $locationRef.id
    reference_type = "WIDE"
    is_primary = $true
    sort_order = 1
  } | Out-Null
  $style = Invoke-Api "POST" "/projects/$ProjectId/style-profiles" @{
    name = "Ink Continuity"
    positive_prompt = "delicate ink"
    negative_prompt = "muddy colors"
    rendering_style = "clean cinematic ink"
    camera_language = "patient camera"
  }
  $revision = Invoke-Api "POST" "/shots/$ShotId/spec/revisions" @{
    reason = "structured e2e setup"
    changes = @{
      location_id = $location.id
      style_profile_id = $style.id
      summary = "Mira approaches the harbor gate"
      action = "raises the lantern"
      composition = "center frame"
      camera_movement = "slow dolly"
      props = @("brass lantern")
    }
    characters = @(
      @{
        character_id = $character.id
        role = "PRIMARY"
        sort_order = 1
        action = "holds the lantern near her face"
        reference_asset_ids = @($characterRef.id)
      }
    )
  }
  if ($revision.new_spec_revision -ne 2) { Fail "structured" "Expected ShotSpec revision 2 after structured setup." }
  $spec = Invoke-Api "GET" "/shots/$ShotId/spec"
  if ($spec.compiler_version -ne "structured-continuity-v1") { Fail "structured" "Unexpected compiler version." }
  if ([string]$spec.compiled_prompt -notmatch "white coat") { Fail "structured" "Compiled prompt does not include the character snapshot." }
  if (@($spec.reference_asset_ids).Count -lt 2) { Fail "structured" "Expected character and location references in ShotSpec." }
  $initialPromptHash = Get-StringSha256 $spec.compiled_prompt
  $initialPayloadHash = Get-StringSha256 $spec.structured_payload_json

  $oldRequest = Invoke-Api "POST" "/shots/$ShotId/keyframe/generate" @{ provider_id = "fake-http"; seed = 91 }
  Wait-TaskStatus $ProjectId $oldRequest.id @("SUCCEEDED") 120 | Out-Null
  Wait-ShotStatus $ProjectId $ShotId "KEYFRAME_REVIEW" 60 | Out-Null
  Assert-ProviderKeyframeRequest $oldRequest.id "white coat"
  $detail = Get-Detail $ProjectId
  $oldRequestDetail = Get-RequestById $detail $oldRequest.id
  if ($oldRequestDetail.shot_spec_revision -ne 2 -or $oldRequestDetail.compiler_version -ne "structured-continuity-v1") {
    Fail "structured" "GenerationRequest did not persist the ShotSpec snapshot."
  }
  if ((Get-StringSha256 $oldRequestDetail.prompt_snapshot) -ne $initialPromptHash) {
    Fail "structured" "GenerationRequest prompt snapshot does not match ShotSpec."
  }
  if ((Get-StringSha256 $oldRequestDetail.structured_payload_json) -ne $initialPayloadHash) {
    Fail "structured" "GenerationRequest structured payload snapshot does not match ShotSpec."
  }

  Invoke-Api "PATCH" "/characters/$($character.id)" @{
    appearance = "black coat"
    default_clothing = "black coat"
  } | Out-Null
  $unchanged = Invoke-Api "GET" "/shots/$ShotId/spec"
  if ((Get-StringSha256 $unchanged.compiled_prompt) -ne $initialPromptHash) {
    Fail "structured" "Character template edit changed the current ShotSpec without sync."
  }
  if ([string]$unchanged.compiled_prompt -match "black coat") {
    Fail "structured" "Current ShotSpec read mutable Character defaults after edit."
  }

  $synced = Invoke-Api "POST" "/shots/$ShotId/spec/sync" @{
    reason = "sync character defaults"
    sync_character_defaults = $true
    sync_location_defaults = $false
    sync_style_profile = $false
  }
  if ($synced.new_spec_revision -ne 3) { Fail "structured" "Expected explicit sync to create revision 3." }
  $newSpec = Invoke-Api "GET" "/shots/$ShotId/spec"
  if ([string]$newSpec.compiled_prompt -notmatch "black coat") { Fail "structured" "Synced ShotSpec did not use updated Character defaults." }
  $Summary.structured_continuity = [ordered]@{
    character_id = $character.id
    character_reference_asset_id = $characterRef.id
    location_id = $location.id
    location_reference_asset_id = $locationRef.id
    style_profile_id = $style.id
    old_shot_spec_revision = 2
    shot_spec_id = $newSpec.id
    shot_spec_revision = $newSpec.revision
    compiler_version = $newSpec.compiler_version
    compiled_prompt_sha256 = Get-StringSha256 $newSpec.compiled_prompt
    structured_payload_sha256 = Get-StringSha256 $newSpec.structured_payload_json
    generation_request_id = $oldRequest.id
    generation_request_revision = $oldRequestDetail.shot_spec_revision
    old_request_prompt_sha256 = Get-StringSha256 $oldRequestDetail.prompt_snapshot
    provider_reference_asset_ids = @($newSpec.reference_asset_ids)
    sync_invalidated_asset_ids = @($synced.invalidated_asset_ids)
    contract_status = "CONTRACT_VERIFIED_ONLY"
  }
}

function Create-ScriptStoryboardShots($ProjectId) {
  Write-Host "==> Script import and storyboard apply"
  $character = Invoke-Api "POST" "/projects/$ProjectId/characters" @{
    name = "Script Alice"
    appearance = "calm engineer with silver glasses"
    default_clothing = "white lab coat"
    continuity_notes = "Manually matched from ShotDraft; not auto-created by parser."
  }
  $location = Invoke-Api "POST" "/projects/$ProjectId/locations" @{
    name = "Script Lab"
    description = "A practical lab with a sealed door"
    time_of_day = "Night"
    lighting = "cool overhead panels"
  }
  $style = Invoke-Api "POST" "/projects/$ProjectId/style-profiles" @{
    name = "Script Ink"
    positive_prompt = "clean ink storyboard frame"
    negative_prompt = "blurred details"
    aspect_ratio = "16:9"
  }
  $scriptText = @"
INT. SCRIPT LAB - NIGHT
ALICE
I will open the door.

EXT. SCRIPT STREET - DAY
A vehicle stops near the curb.

EXT. SCRIPT ROOFTOP - NIGHT
ALICE: The wind is too strong.
"@
  $script = Invoke-Api "POST" "/projects/$ProjectId/scripts/import" @{
    title = "3C-2 E2E Script"
    text = $scriptText
    source_type = "FOUNTAIN"
    language = "mixed"
  }
  $parsed = Invoke-Api "POST" "/scripts/$($script.id)/parse"
  if ($parsed.parser_version -ne "deterministic-script-parser-v1") { Fail "script" "Unexpected parser version." }
  $blocks = @((Invoke-Api "GET" "/scripts/$($script.id)/blocks") | ForEach-Object { $_ })
  if ([int]$parsed.block_count -lt 7) { Fail "script" "Expected parsed script blocks." }
  $storyboard = Invoke-Api "POST" "/scripts/$($script.id)/storyboards" @{
    name = "3C-2 E2E Storyboard"
    default_style_profile_id = $style.id
  }
  $drafts = @((Invoke-Api "GET" "/storyboards/$($storyboard.id)/shot-drafts") | ForEach-Object { $_ })
  if ($drafts.Count -lt 3) { Fail "storyboard" "Expected at least three ShotDrafts." }
  $firstDraft = $drafts[0]
  $split = @((Invoke-Api "POST" "/shot-drafts/$($firstDraft.id)/split" @{ split_after_block_id = $firstDraft.source_block_start_id }) | ForEach-Object { $_ })
  if ($split.Count -ne 2) { Fail "storyboard" "ShotDraft split did not return two drafts." }
  $merged = Invoke-Api "POST" "/shot-drafts/$($split[0].id)/merge-next"
  if (-not $merged.id) { Fail "storyboard" "ShotDraft merge did not return a draft." }
  $drafts = @((Invoke-Api "GET" "/storyboards/$($storyboard.id)/shot-drafts") | ForEach-Object { $_ })
  $firstDraft = $drafts[0]
  $updatedDraft = Invoke-Api "PATCH" "/shot-drafts/$($firstDraft.id)" @{
    location_id = $location.id
    style_profile_id = $style.id
    free_prompt = "Manual review keeps Alice framed before the door opens."
    characters = @(
      @{
        character_id = $character.id
        character_name = "ALICE"
        role = "PRIMARY"
        sort_order = 0
      }
    )
  }
  $preview = Invoke-Api "POST" "/shot-drafts/$($updatedDraft.id)/preview-spec"
  if ($preview.compiler_version -ne "structured-continuity-v1") { Fail "storyboard" "Preview did not reuse Prompt Compiler." }
  if ([string]$preview.compiled_prompt -notmatch "silver glasses") { Fail "storyboard" "Preview prompt did not include matched Character." }
  $draftIds = @($drafts | Select-Object -First 3 | ForEach-Object { $_.id })
  $applied = Invoke-Api "POST" "/storyboards/$($storyboard.id)/apply" @{ shot_draft_ids = $draftIds }
  $shotIds = @($applied.applied_shot_ids)
  if ($shotIds.Count -ne 3) { Fail "storyboard" "Expected storyboard apply to create three Shots." }
  $specHashes = @()
  $specIds = @()
  foreach ($shotId in $shotIds) {
    $spec = Invoke-Api "GET" "/shots/$shotId/spec"
    if ($spec.revision -ne 1) { Fail "storyboard" "Applied ShotSpec revision is not 1." }
    if ($spec.compiler_version -ne "structured-continuity-v1") { Fail "storyboard" "Applied ShotSpec compiler version mismatch." }
    $specIds += $spec.id
    $specHashes += Get-StringSha256 $spec.compiled_prompt
  }
  $Summary.script_storyboard = [ordered]@{
    script_document_id = $script.id
    script_sha256 = $script.content_sha256
    script_block_count = [int]$parsed.block_count
    script_parser_version = $parsed.parser_version
    storyboard_id = $storyboard.id
    shot_draft_ids = $draftIds
    applied_shot_ids = $shotIds
    compiled_prompt_hashes = $specHashes
    shot_spec_ids = $specIds
    preview_compiler_version = $preview.compiler_version
    character_id = $character.id
    location_id = $location.id
    style_profile_id = $style.id
    backup_restore_verified = $false
  }
  return $shotIds
}

function Complete-Shot($ProjectId, $ShotId, [int]$ShotNumber, [bool]$RestartGenerationWorker) {
  Write-Host "==> Shot $ShotNumber keyframe"
  $keyRequest = Invoke-Api "POST" "/shots/$ShotId/keyframe/generate" @{ provider_id = "fake-http"; seed = (100 + $ShotNumber) }
  $restartInfo = $null
  if ($RestartGenerationWorker -and -not $SkipWorkerRestart) {
    $running = Wait-TaskStatus $ProjectId $keyRequest.id @("RUNNING") 30
    $beforeDetail = $running[0]
    $beforeTask = $running[1]
    if (-not $beforeTask.remote_job_id) { Fail "worker-restart" "RUNNING task has no remote_job_id." }
    $beforeStats = Get-FakeStats
    Stop-TrackedService "generation-worker"
    Start-Sleep -Seconds 1
    Start-RestartedGenerationWorker
    $after = Wait-TaskStatus $ProjectId $keyRequest.id @("SUCCEEDED") 120
    $afterTask = $after[1]
    $afterStats = Get-FakeStats
    if ($afterTask.id -ne $beforeTask.id) { Fail "worker-restart" "Task ID changed across worker restart." }
    if ($afterTask.remote_job_id -ne $beforeTask.remote_job_id) { Fail "worker-restart" "remote_job_id changed across worker restart." }
    $sameRequestTasks = @($after[0].tasks | Where-Object { $_.generation_request_id -eq $keyRequest.id })
    if ($sameRequestTasks.Count -ne 1) { Fail "worker-restart" "Expected one task for restarted request; got $($sameRequestTasks.Count)." }
    if ([int]$afterStats.created_jobs -ne [int]$beforeStats.created_jobs) {
      Fail "worker-restart" "Worker restart resubmitted the RUNNING task."
    }
    $restartInfo = [ordered]@{
      request_id = $keyRequest.id
      before_task_id = $beforeTask.id
      after_task_id = $afterTask.id
      remote_job_id = $afterTask.remote_job_id
      before_attempt_number = $beforeTask.attempt_number
      after_attempt_number = $afterTask.attempt_number
      before_retry_count = $beforeTask.retry_count
      after_retry_count = $afterTask.retry_count
      before_created_jobs = $beforeStats.created_jobs
      after_created_jobs = $afterStats.created_jobs
    }
    $Summary.worker_restart = $restartInfo
  } else {
    Wait-TaskStatus $ProjectId $keyRequest.id @("SUCCEEDED") 120 | Out-Null
  }

  $keyReady = Wait-ShotStatus $ProjectId $ShotId "KEYFRAME_REVIEW" 60
  $detail = $keyReady[0]
  $shot = $keyReady[1]
  if (-not $shot.target_keyframe.asset_id) { Fail "shot:$ShotId" "Keyframe asset is missing." }
  $keyAsset = Get-AssetById $detail $shot.target_keyframe.asset_id
  Assert-MediaRange $shot.target_keyframe.url $keyAsset.file_size "shot-$ShotNumber-keyframe" | Out-Null

  Invoke-Api "POST" "/shots/$ShotId/keyframe/approve" | Out-Null
  Wait-ShotStatus $ProjectId $ShotId "KEYFRAME_APPROVED" 30 | Out-Null

  Write-Host "==> Shot $ShotNumber video"
  $videoRequest = Invoke-Api "POST" "/shots/$ShotId/video/generate" @{ provider_id = "fake-http"; seed = (200 + $ShotNumber); duration_seconds = 1.0 }
  Wait-TaskStatus $ProjectId $videoRequest.id @("SUCCEEDED") 120 | Out-Null
  $videoReady = Wait-ShotStatus $ProjectId $ShotId "VIDEO_REVIEW" 60
  $detail = $videoReady[0]
  $shot = $videoReady[1]
  $videoAsset = @($detail.assets | Where-Object { $_.shot_id -eq $ShotId -and $_.type -eq "VIDEO" } | Sort-Object id -Descending | Select-Object -First 1)[0]
  if (-not $videoAsset) { Fail "shot:$ShotId" "Video asset is missing." }
  Assert-MediaRange $videoAsset.url $videoAsset.file_size "shot-$ShotNumber-video" | Out-Null
  $qualityChecks = @()
  $qualityDeadline = (Get-Date).AddSeconds(30)
  while ((Get-Date) -lt $qualityDeadline) {
    $qualityDetail = Invoke-Api "GET" "/projects/$ProjectId"
    $qualityChecks = @($qualityDetail.quality_checks | Where-Object { $_.shot_id -eq $ShotId -and $_.asset_id -eq $videoAsset.id })
    if ($qualityChecks.Count -ge 2) { break }
    Start-Sleep -Milliseconds 500
  }
  if ($qualityChecks.Count -lt 2) { Fail "shot:$ShotId" "Quality checks were not generated for video review." }
  $durationCheck = @($qualityChecks | Where-Object { $_.check_type -eq "DURATION_DEVIATION" -and $_.asset_id -eq $videoAsset.id })[0]
  if (-not $durationCheck -or -not $durationCheck.algorithm_version) { Fail "shot:$ShotId" "Quality checks are not tied to the current video asset." }
  $tailTargetChecks = @($qualityChecks | Where-Object { $_.check_type -like "TAIL_TARGET_*" })
  if ($tailTargetChecks.Count -lt 1) { Fail "shot:$ShotId" "Quality checks did not compare the tail frame to the target keyframe." }
  $startAnchorChecks = @($qualityChecks | Where-Object { $_.check_type -like "START_ANCHOR_*" })
  if ($ShotNumber -gt 1 -and $startAnchorChecks.Count -lt 1) { Fail "shot:$ShotId" "Quality checks did not compare the inherited start frame." }
  if ($shot.status -ne "VIDEO_REVIEW") { Fail "shot:$ShotId" "Quality checks changed the review state." }
  Assert-ProviderVideoRequest $videoRequest $ShotNumber

  Invoke-Api "POST" "/shots/$ShotId/video/approve" | Out-Null
  $completed = Wait-ShotStatus $ProjectId $ShotId "COMPLETED" 60
  $detail = $completed[0]
  $shot = $completed[1]
  if (-not $shot.locked_tail_frame.asset_id) { Fail "shot:$ShotId" "Locked tail frame is missing." }
  $tailAsset = Get-AssetById $detail $shot.locked_tail_frame.asset_id
  Assert-MediaRange $shot.locked_tail_frame.url $tailAsset.file_size "shot-$ShotNumber-tail" | Out-Null

  $keyTask = Get-TaskForRequest $detail $keyRequest.id
  $videoTask = Get-TaskForRequest $detail $videoRequest.id
  $startFrameAsset = if ($shot.start_frame_asset_id) { Get-AssetById $detail $shot.start_frame_asset_id } else { $null }
  if ($keyTask.status -ne "SUCCEEDED" -or -not $keyTask.result_asset_id) { Fail "shot:$ShotId" "Keyframe task did not persist a result asset." }
  if ($videoTask.status -ne "SUCCEEDED" -or -not $videoTask.result_asset_id) { Fail "shot:$ShotId" "Video task did not persist a result asset." }
  $shotAssets = @($detail.assets | Where-Object { $_.shot_id -eq $ShotId })
  $qualityTypes = @($qualityChecks | ForEach-Object { $_.check_type } | Sort-Object -Unique)
  $qualityVersions = @($qualityChecks | ForEach-Object { $_.algorithm_version } | Sort-Object -Unique)
  $qualityWarnings = @($qualityChecks | Where-Object { $_.severity -eq "WARNING" })
  $qualityErrors = @($qualityChecks | Where-Object { $_.severity -eq "ERROR" })

  $Summary.shots += [ordered]@{
    shot_id = $ShotId
    shot_number = $ShotNumber
    final_status = $shot.status
    keyframe_asset_id = $shot.target_keyframe.asset_id
    video_asset_id = $videoAsset.id
    tail_asset_id = $shot.locked_tail_frame.asset_id
    start_frame_source_shot_id = if ($shot.start_frame) { $shot.start_frame.source_shot_id } else { $null }
    start_frame_source_asset_id = if ($startFrameAsset) { $startFrameAsset.source_asset_id } else { $null }
    keyframe_request_id = $keyRequest.id
    keyframe_task_id = $keyTask.id
    video_request_id = $videoRequest.id
    video_task_id = $videoTask.id
    video_generation_mode = $videoRequest.generation_mode
    quality_asset_id = $videoAsset.id
    quality_result_count = $qualityChecks.Count
    quality_check_types = $qualityTypes
    quality_algorithm_versions = $qualityVersions
    quality_warning_count = $qualityWarnings.Count
    quality_error_count = $qualityErrors.Count
    quality_tail_target_count = $tailTargetChecks.Count
    quality_start_anchor_count = $startAnchorChecks.Count
    asset_revision_count = @($shotAssets | Where-Object { $null -ne $_.revision } | ForEach-Object { $_.revision } | Sort-Object -Unique).Count
    superseded_asset_count = @($shotAssets | Where-Object { $_.status -eq "SUPERSEDED" }).Count
  }
}

function Invoke-SqliteCheck($DbPath, $ProjectId, $RenderId) {
  $env:FCS_SQLITE_PATH = $DbPath
  $env:FCS_EXPECT_PROJECT_ID = $ProjectId
  $env:FCS_EXPECT_RENDER_ID = $RenderId
  Push-Location $BackendRoot
  try {
    $json = @'
import json
import os
import sqlite3

db_path = os.environ["FCS_SQLITE_PATH"]
project_id = int(os.environ["FCS_EXPECT_PROJECT_ID"])
render_id = int(os.environ["FCS_EXPECT_RENDER_ID"])
with sqlite3.connect(db_path) as conn:
    quick_check = conn.execute("PRAGMA quick_check").fetchone()[0]
    project_count = conn.execute("SELECT COUNT(*) FROM project WHERE id = ?", (project_id,)).fetchone()[0]
    shot_count = conn.execute("SELECT COUNT(*) FROM shot WHERE project_id = ?", (project_id,)).fetchone()[0]
    task_count = conn.execute("SELECT COUNT(*) FROM generationtask WHERE project_id = ?", (project_id,)).fetchone()[0]
    render_count = conn.execute("SELECT COUNT(*) FROM projectrender WHERE id = ? AND project_id = ?", (render_id, project_id)).fetchone()[0]
    asset_count = conn.execute("SELECT COUNT(*) FROM asset WHERE project_id = ?", (project_id,)).fetchone()[0]
    superseded_asset_count = conn.execute("SELECT COUNT(*) FROM asset WHERE project_id = ? AND status = 'SUPERSEDED'", (project_id,)).fetchone()[0]
    asset_revision_count = conn.execute("SELECT COUNT(DISTINCT revision) FROM asset WHERE project_id = ? AND shot_id IS NOT NULL", (project_id,)).fetchone()[0]
    quality_count = conn.execute("SELECT COUNT(*) FROM qualitycheckresult WHERE project_id = ?", (project_id,)).fetchone()[0]
    quality_duplicate_count = conn.execute("""
        SELECT COUNT(*) FROM (
            SELECT asset_id, COALESCE(reference_asset_id, -1), check_type, algorithm_version, COUNT(*) AS count
            FROM qualitycheckresult
            WHERE project_id = ?
            GROUP BY asset_id, COALESCE(reference_asset_id, -1), check_type, algorithm_version
            HAVING COUNT(*) > 1
        )
    """, (project_id,)).fetchone()[0]
print(json.dumps({
    "quick_check": quick_check,
    "project_count": project_count,
    "shot_count": shot_count,
    "task_count": task_count,
    "render_count": render_count,
    "asset_count": asset_count,
    "asset_revision_count": asset_revision_count,
    "superseded_asset_count": superseded_asset_count,
    "quality_count": quality_count,
    "quality_duplicate_count": quality_duplicate_count,
}, sort_keys=True))
'@ | python -
    return $json | ConvertFrom-Json
  } finally {
    Pop-Location
    Remove-Item Env:FCS_SQLITE_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:FCS_EXPECT_PROJECT_ID -ErrorAction SilentlyContinue
    Remove-Item Env:FCS_EXPECT_RENDER_ID -ErrorAction SilentlyContinue
  }
}

function Run-BackupRestoreVerification($ProjectId, $RenderId, $RenderUrl, $RenderSize) {
  Write-Host "==> Backup same E2E database"
  $env:FCS_DATABASE_URL = $DatabaseUrl
  $backupOutput = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "backup.ps1") -OutputDir $BackupDir -SourceDatabaseUrl $DatabaseUrl
  if ($LASTEXITCODE -ne 0) { Fail "backup" "backup.ps1 failed." }
  $backupLine = @($backupOutput | Where-Object { $_ -like "backup=*" })[0]
  if (-not $backupLine) { Fail "backup" "backup.ps1 did not print a backup path." }
  $backupPath = $backupLine.Substring("backup=".Length)
  if (-not (Test-Path $backupPath)) { Fail "backup" "Backup file does not exist: $backupPath" }
  if ((Get-Item $backupPath).Length -le 0) { Fail "backup" "Backup file is empty: $backupPath" }
  $backupCheck = Invoke-SqliteCheck $backupPath $ProjectId $RenderId
  if ($backupCheck.quick_check -ne "ok" -or $backupCheck.project_count -ne 1 -or $backupCheck.render_count -ne 1 -or $backupCheck.quality_count -lt 1 -or $backupCheck.quality_duplicate_count -ne 0) {
    Fail "backup" "Backup DB did not contain the expected project/render/quality state."
  }

  Write-Host "==> Restore same project/render into isolated DB"
  Stop-TrackedServices
  $script:ProcessItems = @()
  Save-PidFile
  Wait-FileUnlocked $DatabasePath
  Move-Item -LiteralPath $DatabasePath -Destination "$DatabasePath.before-restore" -Force
  Set-Content -Path $DatabasePath -Value "not sqlite" -Encoding ASCII
  $restoreOutput = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "restore.ps1") -BackupPath $backupPath -DestinationDatabaseUrl $DatabaseUrl -Force
  if ($LASTEXITCODE -ne 0) { Fail "restore" "restore.ps1 failed." }
  $restoreCheck = Invoke-SqliteCheck $DatabasePath $ProjectId $RenderId
  if ($restoreCheck.quick_check -ne "ok" -or $restoreCheck.project_count -ne 1 -or $restoreCheck.shot_count -ne 3 -or $restoreCheck.task_count -ne 7 -or $restoreCheck.render_count -ne 1 -or $restoreCheck.quality_count -lt 1 -or $restoreCheck.quality_duplicate_count -ne 0) {
    Fail "restore" "Restored DB did not contain expected project/render/task/quality counts."
  }

  Restart-Stack
  $detail = Get-Detail $ProjectId
  if ($detail.shots.Count -ne 3 -or $detail.tasks.Count -ne 7) { Fail "restore" "Restored API detail has unexpected shot/task counts." }
  if (@($detail.quality_checks).Count -lt 1) { Fail "restore" "Restored API detail is missing quality checks." }
  if ($Summary.script_storyboard) {
    $restoredScript = Invoke-Api "GET" "/scripts/$($Summary.script_storyboard.script_document_id)"
    $restoredBlocks = @((Invoke-Api "GET" "/scripts/$($Summary.script_storyboard.script_document_id)/blocks") | ForEach-Object { $_ })
    $restoredStoryboard = Invoke-Api "GET" "/storyboards/$($Summary.script_storyboard.storyboard_id)"
    $restoredDrafts = @((Invoke-Api "GET" "/storyboards/$($Summary.script_storyboard.storyboard_id)/shot-drafts") | ForEach-Object { $_ })
    if ($restoredScript.content_sha256 -ne $Summary.script_storyboard.script_sha256) { Fail "restore" "Restored script SHA mismatch." }
    if ($restoredBlocks.Count -ne $Summary.script_storyboard.script_block_count) { Fail "restore" "Restored script block count mismatch." }
    if ($restoredStoryboard.id -ne $Summary.script_storyboard.storyboard_id) { Fail "restore" "Restored storyboard mismatch." }
    $appliedDrafts = @($restoredDrafts | Where-Object { $_.applied_shot_id })
    if ($appliedDrafts.Count -lt 3) { Fail "restore" "Restored ShotDraft applied_shot_id links are missing." }
    $Summary.script_storyboard.backup_restore_verified = $true
  }
  $render = Invoke-Api "GET" "/renders/$RenderId"
  if ($render.status -ne "SUCCEEDED" -or -not $render.output_asset_id) { Fail "restore" "Restored render did not remain succeeded." }
  Assert-MediaRange $RenderUrl $RenderSize "restored-render" | Out-Null
  $Summary.backup_restore = [ordered]@{
    backup_path = $backupPath.Replace([string]$ProjectRoot, ".")
    backup_quick_check = $backupCheck.quick_check
    backup_project_id = $ProjectId
    backup_render_id = $RenderId
    backup_asset_count = $backupCheck.asset_count
    backup_quality_count = $backupCheck.quality_count
    backup_quality_duplicate_count = $backupCheck.quality_duplicate_count
    restored_quick_check = $restoreCheck.quick_check
    restored_project_id = $ProjectId
    restored_render_id = $RenderId
    restored_shot_count = $detail.shots.Count
    restored_task_count = $detail.tasks.Count
    restored_asset_count = $restoreCheck.asset_count
    restored_asset_revision_count = $restoreCheck.asset_revision_count
    restored_superseded_asset_count = $restoreCheck.superseded_asset_count
    restored_quality_count = $restoreCheck.quality_count
    restored_quality_duplicate_count = $restoreCheck.quality_duplicate_count
    restored_api_quality_count = @($detail.quality_checks).Count
    restored_render_status = $render.status
  }
}

try {
  New-Item -ItemType Directory -Force -Path $RunRoot, $LogRoot, $StorageDir, $BackupDir | Out-Null
  Require-Command python
  Require-Command node
  Require-Command npm.cmd
  Require-Command ffmpeg
  Require-Command ffprobe
  Require-Command curl.exe
  Test-PortFree $FrontendPort "frontend"
  Test-PortFree $BackendPort "backend"
  Test-PortFree $FakeProviderPort "fake-provider"
  if (-not (Test-Path (Join-Path $FrontendRoot "node_modules"))) { Fail "preflight" "Frontend dependencies are not installed. Run npm install in frontend." }

  $providerJson = Get-Content (Join-Path $BackendRoot "provider-config.example.json") -Raw
  $providerJson = $providerJson -replace "http://127\.0\.0\.1:8090", "http://127.0.0.1:$FakeProviderPort"
  Set-Content -Path $ProviderConfig -Value $providerJson -Encoding UTF8

  Push-Location $BackendRoot
  try {
    $env:FCS_DATABASE_URL = $DatabaseUrl
    python -m alembic upgrade head
  } finally {
    Pop-Location
  }

  Start-Stack
  Invoke-RestMethod -Method POST -Uri "$FakeBaseUrl/test/reset" -TimeoutSec 5 | Out-Null

  Write-Host "==> Create isolated 3C-2 E2E project"
  $project = Invoke-Api "POST" "/projects" @{
    name = "3C-2 local E2E $(Get-Date -Format yyyyMMdd-HHmmss)"
    description = "Created by scripts/e2e-local.ps1"
    image_provider_id = "fake-http"
    video_provider_id = "fake-http"
    image_model = "fake-image"
    video_model = "fake-video"
    default_aspect_ratio = "16:9"
    default_video_duration_seconds = 1.0
    default_seed = 7
  }
  $Summary.project_id = $project.id
  Configure-ProviderCostLedger $project.id

  $shotIds = @(Create-ScriptStoryboardShots $project.id)
  $Summary.shot_ids = $shotIds

  Configure-StructuredShot $project.id $shotIds[0]
  Complete-Shot $project.id $shotIds[0] 1 $true
  Complete-Shot $project.id $shotIds[1] 2 $false
  Complete-Shot $project.id $shotIds[2] 3 $false
  Assert-UsageCostLedger $project.id

  $detail = Get-Detail $project.id
  if ($detail.completion.can_render -ne $true) { Fail "completion" "Project is not renderable after three completed shots." }
  $first = @($detail.shots | Where-Object { $_.id -eq $shotIds[0] })[0]
  $second = @($detail.shots | Where-Object { $_.id -eq $shotIds[1] })[0]
  $third = @($detail.shots | Where-Object { $_.id -eq $shotIds[2] })[0]
  $secondStartAsset = Get-AssetById $detail $second.start_frame_asset_id
  $thirdStartAsset = Get-AssetById $detail $third.start_frame_asset_id
  if ($second.start_frame.source_shot_id -ne $shotIds[0]) { Fail "inheritance" "Shot 2 did not inherit Shot 1 tail frame." }
  if ($secondStartAsset.source_asset_id -ne $first.locked_tail_frame.asset_id) { Fail "inheritance" "Shot 2 source asset does not match Shot 1 tail." }
  if ($third.start_frame.source_shot_id -ne $shotIds[1]) { Fail "inheritance" "Shot 3 did not inherit Shot 2 tail frame." }
  if ($thirdStartAsset.source_asset_id -ne $second.locked_tail_frame.asset_id) { Fail "inheritance" "Shot 3 source asset does not match Shot 2 tail." }

  Write-Host "==> Final project render"
  $render = Invoke-Api "POST" "/projects/$($project.id)/renders" $null @{ "Idempotency-Key" = "e2e-render-$($project.id)" }
  $render = Wait-RenderStatus $render.id @("SUCCEEDED") 180
  if (-not $render.output_asset_id -or -not $render.output_url) { Fail "render" "Render succeeded without output asset." }
  $detail = Get-Detail $project.id
  $renderAsset = Get-AssetById $detail $render.output_asset_id
  $renderPath = Assert-MediaRange $render.output_url $renderAsset.file_size "project-render"
  $ffprobeJson = & ffprobe -v error -show_streams -show_format -of json $renderPath
  if ($LASTEXITCODE -ne 0) { Fail "ffprobe" "ffprobe failed for final render." }
  $probe = ($ffprobeJson -join "`n") | ConvertFrom-Json
  $videoStream = @($probe.streams | Where-Object { $_.codec_type -eq "video" })[0]
  $audioStreams = @($probe.streams | Where-Object { $_.codec_type -eq "audio" })
  if (-not $videoStream) { Fail "ffprobe" "Final render has no video stream." }
  if ($audioStreams.Count -ne 0) { Fail "ffprobe" "Final render unexpectedly contains audio streams." }
  if ([int]$videoStream.width -ne 1920 -or [int]$videoStream.height -ne 1080) { Fail "ffprobe" "Final render dimensions are not 1920x1080." }
  if ([double]$probe.format.duration -le 0) { Fail "ffprobe" "Final render duration is not positive." }
  if ([string]$videoStream.avg_frame_rate -ne "24/1") { Fail "ffprobe" "Final render fps is not 24/1." }

  $Summary.render = [ordered]@{
    id = $render.id
    status = $render.status
    output_asset_id = $render.output_asset_id
    output_url = $render.output_url
    file_size = $renderAsset.file_size
  }
  $Summary.ffprobe = [ordered]@{
    duration_seconds = [double]$probe.format.duration
    width = [int]$videoStream.width
    height = [int]$videoStream.height
    avg_frame_rate = [string]$videoStream.avg_frame_rate
    codec = [string]$videoStream.codec_name
    audio_streams = $audioStreams.Count
  }

  Run-BackupRestoreVerification $project.id $render.id $render.output_url $renderAsset.file_size

  Write-Host ""
  Write-Host "E2E local isolated validation passed."
  $Summary.provider_usage = $script:ProviderUsageEvidence
  $Summary | ConvertTo-Json -Depth 12
} catch {
  $OriginalError = $_
  Write-Error $_
  throw
} finally {
  Stop-TrackedServices
  if ($OriginalError) {
    Write-Host "Run root retained for diagnostics: $RunRoot"
  } else {
    Write-Host "Run root retained for evidence: $RunRoot"
  }
}
