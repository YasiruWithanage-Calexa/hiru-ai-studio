# Start every Cloud Run function locally with functions-framework, one window each.
# Ports must match api/workers/task_manager.FUNCTIONS. Run from the repo root:
#   powershell -File scripts\start-functions.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"

$functions = @(
    @{ Name = "hiru-echo"; Source = "src\services\echo"; Port = 8201 },
    @{ Name = "hiru-doc-ingest"; Source = "src\services\doc_ingest"; Port = 8202 }
)

# Functions read SUPABASE__* from the environment; load them from .env.
Get-Content (Join-Path $root ".env") | Where-Object { $_ -match '^\s*[A-Z_]+=' } | ForEach-Object {
    $k, $v = $_ -split '=', 2
    [Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim(), "Process")
}
# `contracts` is importable from the editable install; the service folder goes on PYTHONPATH.
foreach ($f in $functions) {
    $src = Join-Path $root $f.Source
    $env:PYTHONPATH = $src
    Start-Process -FilePath $python -ArgumentList @(
        "-m", "functions_framework", "--target", "handle", "--source", (Join-Path $src "main.py"),
        "--port", $f.Port, "--debug") -WorkingDirectory $src
    Write-Host "$($f.Name) on http://localhost:$($f.Port)"
}
