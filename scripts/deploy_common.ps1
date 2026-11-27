# Shared by deploy_api.ps1, deploy_functions.ps1 and deploy_assemble.ps1 (plan/2026-11-27). Dot-sourced, not run.
# Windows PowerShell 5.1. Keep this file ASCII: 5.1 reads a script without a BOM in the machine's code page.

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

# A native tool's failure does not stop PowerShell by itself.
function Invoke-Tool {
    param([Parameter(Mandatory)][string]$Tool, [Parameter(Mandatory)][string[]]$Arguments, [switch]$DryRun)
    if ($DryRun) { Write-Host "  [dry run] $Tool $($Arguments -join ' ')"; return }
    # gcloud and docker write progress to stderr: with "Stop", 5.1 can take a redirected line for a failure. The exit
    # code decides.
    $ErrorActionPreference = "Continue"
    & $Tool @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Tool failed with exit code $LASTEXITCODE" }
}

# `terraform output -json deploy`, or the same JSON from a file (-Outputs), so a dry run needs no cloud and no state.
function Get-DeployOutputs {
    param([string]$Outputs)
    if ($Outputs) { return Get-Content -Raw -Encoding UTF8 $Outputs | ConvertFrom-Json }
    # Terraform's state is in a bucket. It reads it with a short-lived token of the signed-in gcloud account, so the
    # machine's application default credentials (which may belong to other work) are neither used nor replaced.
    if (-not $env:GOOGLE_OAUTH_ACCESS_TOKEN) {
        $env:GOOGLE_OAUTH_ACCESS_TOKEN = & gcloud auth print-access-token --quiet
        if ($LASTEXITCODE -ne 0) { throw "gcloud is not signed in: gcloud auth login" }
    }
    $json = & terraform "-chdir=$(Join-Path $RepoRoot 'infra\terraform')" output -json deploy
    if ($LASTEXITCODE -ne 0) { throw "terraform output failed: run terraform init and apply first" }
    return $json | Out-String | ConvertFrom-Json
}

# infra/env/<environment>.env: the one settings list of the environment (no secrets).
function Get-DeploySettings {
    param([Parameter(Mandatory)][string]$Environment)
    $file = Join-Path $RepoRoot "infra\env\$Environment.env"
    if (-not (Test-Path $file)) { throw "No settings file: $file" }
    $settings = [ordered]@{}
    foreach ($line in Get-Content -Encoding UTF8 $file) {
        $text = $line.Trim()
        if (-not $text -or $text.StartsWith("#")) { continue }
        $key, $value = $text -split "=", 2
        $settings[$key.Trim()] = "$value".Trim()
    }
    return $settings
}

# The media setting must be one the cloud can work with, and name the bucket Terraform made.
function Assert-MediaSettings {
    param([Parameter(Mandatory)]$Settings, [Parameter(Mandatory)]$Outputs)
    $backend = $Settings["FILES__BACKEND"]
    if ($backend -notin @("supabase", "gcs")) { throw "FILES__BACKEND must be supabase or gcs, not '$backend'" }
    if ($Settings["FILES__GCS_BUCKET"] -ne $Outputs.media_bucket) {
        throw "FILES__GCS_BUCKET '$($Settings["FILES__GCS_BUCKET"])' is not the Terraform bucket '$($Outputs.media_bucket)'"
    }
}

# UTF-8 without a BOM and with LF line ends: these files are read on Linux.
function Write-UnixFile {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][AllowEmptyString()][string[]]$Lines)
    $text = (($Lines -join "`n") + "`n") -replace "`r", ""
    [System.IO.File]::WriteAllText($Path, $text, (New-Object System.Text.UTF8Encoding($false)))
}
