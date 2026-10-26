# Start every Cloud Run function locally with functions-framework, one window each.
# No --debug: its reloader restarts a function mid-job (jobs run for minutes) when any watched file
# changes. Restart a function by hand after editing its code.
# Ports must match api/workers/task_manager (FUNCTIONS, and DIRECTOR_CHAT for the streamed chat). Run from the repo root:
#   powershell -File scripts\start-functions.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"

$functions = @(
    @{ Name = "hiru-echo"; Source = "src\services\echo"; Port = 8201 },
    @{ Name = "hiru-doc-ingest"; Source = "src\services\doc_ingest"; Port = 8202 },
    @{ Name = "hiru-script-split"; Source = "src\services\script_split"; Port = 8203 },
    @{ Name = "hiru-structure-build"; Source = "src\services\structure_build"; Port = 8204 },
    @{ Name = "hiru-canon-extract"; Source = "src\services\canon_extract"; Port = 8205 },
    @{ Name = "hiru-director-chat"; Source = "src\services\director_chat"; Port = 8206 },
    @{ Name = "hiru-shot-producer"; Source = "src\services\shot_producer"; Port = 8207 },
    @{ Name = "hiru-frame-render"; Source = "src\services\frame_render"; Port = 8208 }
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
        "-m", "functions_framework", "--target", "handle", "--source", "`"$(Join-Path $src "main.py")`"",
        "--port", $f.Port) -WorkingDirectory $src
    Write-Host "$($f.Name) on http://localhost:$($f.Port)"
}
