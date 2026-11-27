# Build and deploy `assemble` (ffmpeg, Cloud Run) by hand (plan/2026-11-27 D3). Run from the repo root:
#   powershell -File scripts\deploy_assemble.ps1
# Terraform owns the service's settings; this changes only which image runs. Needs Docker running.
param(
    [string]$Environment = "staging",
    [string]$Outputs = "",
    [string]$Tag = "",
    [switch]$DryRun
)
. (Join-Path $PSScriptRoot "deploy_common.ps1")

$out = Get-DeployOutputs $Outputs
if (-not $Tag) { $Tag = Get-Date -Format "yyyyMMdd-HHmmss" }
$image = "$($out.images)/assemble:$Tag"

Invoke-Tool gcloud @("auth", "configure-docker", "$($out.region)-docker.pkg.dev", "--quiet") -DryRun:$DryRun
Invoke-Tool docker @("build", "--platform", "linux/amd64", "-t", $image, (Join-Path $RepoRoot "infra\assemble")) -DryRun:$DryRun
Invoke-Tool docker @("push", $image) -DryRun:$DryRun
Invoke-Tool gcloud @("run", "deploy", $out.assemble_service, "--image", $image,
    "--project", $out.project_id, "--region", $out.region, "--quiet") -DryRun:$DryRun
Write-Host "Done: $image"
