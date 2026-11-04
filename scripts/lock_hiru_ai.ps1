# Re-resolve the hashed requirement sets of the hiru_ai package (plan/2026-11-03 Phase 0).
#   scripts/lock_hiru_ai.ps1               resolve both sets, ignoring releases newer than 7 days
#   scripts/lock_hiru_ai.ps1 -Cutoff 2026-10-27   resolve as of a date (reproducible)
# A fresh release is never picked up unreviewed: bump the pins in requirements/*.in on purpose, read the
# changelog, run `pytest -q` and `python scripts/lint_imports.py`, then commit the .in and .txt together.
param([string]$Cutoff = (Get-Date).ToUniversalTime().AddDays(-7).ToString("yyyy-MM-ddT00:00:00Z"))
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw "uv is required: pip install uv" }
if ($Cutoff -notmatch "T") { $Cutoff = "${Cutoff}T00:00:00Z" }
foreach ($set in "hiru_ai", "hiru_ai_openai") {
    uv pip compile "requirements/$set.in" --generate-hashes --python-version 3.12 --exclude-newer $Cutoff -o "requirements/$set.txt"
}
