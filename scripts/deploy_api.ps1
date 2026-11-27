# Build the API image and roll it out to its VM (plan/2026-11-27, section 2). Run from the repo root:
#   powershell -File scripts\deploy_api.ps1 -FrontendUrl https://<app>.hosted.app
#   powershell -File scripts\deploy_api.ps1 -FrontendUrl ... -Tag 20261127-101500 -SkipBuild     # an earlier image
# It copies compose.yaml, the Caddyfile, the settings and the list of secret NAMES to the VM through Google's tunnel;
# infra/vm/deploy.sh there reads the secret values with the VM's own identity (they never pass through this machine),
# restarts the API, checks /healthz, and puts the previous version back if the new one does not come up.
# Needs Docker running and `gcloud` signed in to the project.
param(
    [Parameter(Mandatory)][string]$FrontendUrl,
    [string]$Environment = "staging",
    [string]$Outputs = "",
    [string]$Tag = "",
    [switch]$SkipBuild,
    [switch]$DryRun
)
. (Join-Path $PSScriptRoot "deploy_common.ps1")

$FrontendUrl = $FrontendUrl.TrimEnd("/")
if ($FrontendUrl -notmatch "^https://[^/]+$") { throw "-FrontendUrl is the site's origin, like https://app.example.com" }
if ($SkipBuild -and -not $Tag) { throw "-SkipBuild needs -Tag: say which image to run" }
$out = Get-DeployOutputs $Outputs
$settings = Get-DeploySettings $Environment
Assert-MediaSettings $settings $out
if (-not $Tag) { $Tag = Get-Date -Format "yyyyMMdd-HHmmss" }
$image = "$($out.images)/api:$Tag"

if (-not $SkipBuild) {
    Invoke-Tool gcloud @("auth", "configure-docker", "$($out.region)-docker.pkg.dev", "--quiet") -DryRun:$DryRun
    Invoke-Tool docker @("build", "--platform", "linux/amd64", "-t", $image, $RepoRoot) -DryRun:$DryRun
    Invoke-Tool docker @("push", $image) -DryRun:$DryRun
}

$work = Join-Path ([System.IO.Path]::GetTempPath()) "hiru-deploy-api"
if (Test-Path $work) { Remove-Item -Recurse -Force $work }
New-Item -ItemType Directory -Force $work | Out-Null

$vars = [ordered]@{}
foreach ($key in $settings.Keys) { $vars[$key] = $settings[$key] }
$vars["SUPABASE__URL"] = $out.supabase_url
$vars["SUPABASE__INVITE_REDIRECT_URL"] = "$FrontendUrl/auth/accept"
$vars["API__CORS_ORIGINS"] = $FrontendUrl
$vars["API__PUBLIC_URL"] = $out.api_url
$vars["GCP__PROJECT_ID"] = $out.project_id
$vars["GCP__REGION"] = $out.region
$vars["GCP__TASKS_QUEUE"] = $out.tasks_queue
$vars["GCP__TASKS_INVOKER_SA"] = $out.tasks_invoker_sa
$vars["GCP__FUNCTIONS_BASE_URL"] = $out.functions_base_url
$vars["ASSEMBLE__URL"] = $out.assemble_url
$vars["FILES__CACHE_DIR"] = "/var/hiru/files"
$vars["FILES__CACHE_MAX_GB"] = "5"
Write-UnixFile (Join-Path $work "settings.env") @($vars.Keys | ForEach-Object { "$_=$($vars[$_])" })

$p = $out.secret_prefix
Write-UnixFile (Join-Path $work "secrets.list") @(
    "SUPABASE__SERVICE_ROLE_KEY=$p-supabase-service-role-key",
    "API__INTERNAL_SECRET=$p-api-internal-secret",
    "ASSEMBLE__SECRET=$p-assemble-secret",
    "OPENAI__API_KEY=$p-openai-api-key",
    "GOOGLE__API_KEY=$p-google-api-key")
Write-UnixFile (Join-Path $work "compose.env") @("API_IMAGE=$image", "API_HOST=$($out.api_host)")
foreach ($name in "compose.yaml", "Caddyfile", "deploy.sh") {
    Write-UnixFile (Join-Path $work $name) @(Get-Content -Encoding UTF8 (Join-Path $RepoRoot "infra\vm\$name"))
}

$vm = @("--project", $out.project_id, "--zone", $out.api_zone, "--tunnel-through-iap")
Invoke-Tool gcloud (@("compute", "ssh", $out.api_vm) + $vm + @("--command", "rm -rf /tmp/hiru-deploy; mkdir -m 700 /tmp/hiru-deploy")) -DryRun:$DryRun
$files = @(Get-ChildItem -File $work | ForEach-Object { $_.FullName })
Invoke-Tool gcloud (@("compute", "scp") + $files + @("$($out.api_vm):/tmp/hiru-deploy/") + $vm) -DryRun:$DryRun
Invoke-Tool gcloud (@("compute", "ssh", $out.api_vm) + $vm + @("--command", "sudo bash /tmp/hiru-deploy/deploy.sh $($out.project_id) $($out.region)")) -DryRun:$DryRun

if ($DryRun) { Write-Host "Dry run: files prepared in $work"; return }
# The certificate of a new host name can take a minute.
foreach ($attempt in 1..20) {
    try {
        Invoke-RestMethod -Uri "$($out.api_url)/healthz" -TimeoutSec 10 | Out-Null
        Write-Host "Done: $($out.api_url) runs $image"
        return
    } catch { Start-Sleep -Seconds 6 }
}
throw "$($out.api_url)/healthz does not answer over HTTPS. The API is up on the VM: check the certificate (docker compose logs caddy)."
