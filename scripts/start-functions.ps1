# Start every Cloud Run function locally with functions-framework, one window each.
# No --debug: its reloader restarts a function mid-job (jobs run for minutes) when any watched file
# changes. Restart a function by hand after editing its code.
# Ports must match api/workers/task_manager (FUNCTIONS, and DIRECTOR_CHAT for the streamed chat). Run from the repo root:
#   powershell -File scripts\start-functions.ps1
# Restart only some (the one already listening on the port is stopped first):
#   powershell -File scripts\start-functions.ps1 -Only hiru-shot-producer,hiru-frame-render
param([string[]]$Only = @())
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
    # plan/2026-11-20d: the Camera agent, the Shot prompt agent and the camera pins live only in the hiru_ai engine
    @{ Name = "hiru-shot-producer"; Source = "src\services\shot_producer"; Port = 8207; Engine = "graph" },
    @{ Name = "hiru-frame-render"; Source = "src\services\frame_render"; Port = 8208; Engine = "graph" },
    @{ Name = "hiru-shot-planner-adam"; Source = "src\services\shot_planner_adam"; Port = 8209 },
    @{ Name = "hiru-shot-planner-david"; Source = "src\services\shot_planner_david"; Port = 8210 },
    @{ Name = "hiru-shot-planner-jonathan"; Source = "src\services\shot_planner_jonathan"; Port = 8211 },
    @{ Name = "hiru-shot-planner-raphael"; Source = "src\services\shot_planner_raphael"; Port = 8215 },
    @{ Name = "hiru-video-render"; Source = "src\services\video_render"; Port = 8212 },
    @{ Name = "hiru-zora-chat"; Source = "src\services\zora_chat"; Port = 8213 },
    @{ Name = "hiru-sable-chat"; Source = "src\services\sable_chat"; Port = 8214 }
)

# AI_ENGINE=legacy (default) | graph picks the engine of a function whose system is migrated (hiru_ai, plan/2026-11-03
# Phase 6). Set it in .env, or per window before starting. A function with `Engine` in the list above always starts on
# that engine, whatever .env says. `hiru_ai` comes from the editable install (pip install -e .),
# as `contracts` does; in the cloud the deploy workflow bundles it into the zips flagged "ai".
# Functions read SUPABASE__* from the environment; load them from .env.
Get-Content (Join-Path $root ".env") | Where-Object { $_ -match '^\s*[A-Z_]+=' } | ForEach-Object {
    $k, $v = $_ -split '=', 2
    $v = $v.Trim()
    if ($v.Length -ge 2 -and ($v[0] -eq '"' -or $v[0] -eq "'") -and $v[-1] -eq $v[0]) { $v = $v.Substring(1, $v.Length - 2) }  # KEY="value" as dotenv reads it
    [Environment]::SetEnvironmentVariable($k.Trim(), $v, "Process")
}
$defaultEngine = if ($env:AI_ENGINE) { $env:AI_ENGINE } else { "legacy" }
if ($Only.Count) {
    $Only = @($Only | ForEach-Object { $_ -split "," } | Where-Object { $_ })
    $known = @($functions.Name) + "hiru-assemble"
    $unknown = @($Only | Where-Object { $_ -notin $known })
    if ($unknown.Count) { throw "No such function: $($unknown -join ', '). Known: $($known -join ', ')" }
}
# `contracts` is importable from the editable install; the service folder goes on PYTHONPATH.
foreach ($f in $functions) {
    if ($Only.Count -and $f.Name -notin $Only) { continue }
    if ($Only.Count) {  # a restart: stop whatever listens on the port now
        Get-NetTCPConnection -LocalPort $f.Port -State Listen -ErrorAction SilentlyContinue |
            ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Milliseconds 500
    }
    $src = Join-Path $root $f.Source
    $env:PYTHONPATH = $src
    $env:AI_ENGINE = if ($f.Engine) { $f.Engine } else { $defaultEngine }
    Start-Process -FilePath $python -ArgumentList @(
        "-m", "functions_framework", "--target", "handle", "--source", "`"$(Join-Path $src "main.py")`"",
        "--port", $f.Port) -WorkingDirectory $src
    Write-Host "$($f.Name) on http://localhost:$($f.Port) (engine: $env:AI_ENGINE)"
}

# infra/assemble (ffmpeg; plan/2026-11-21): a FastAPI service, not a function. The API and hiru-video-render call it at
# ASSEMBLE__URL (http://localhost:8220) with ASSEMBLE__SECRET, both from .env. Needs ffmpeg and ffprobe on the PATH.
$assemblePort = 8220
if ((-not $Only.Count -or "hiru-assemble" -in $Only) -and $env:ASSEMBLE__SECRET) {
    if ($Only.Count) {
        Get-NetTCPConnection -LocalPort $assemblePort -State Listen -ErrorAction SilentlyContinue |
            ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Milliseconds 500
    }
    $assembleDir = Join-Path (Join-Path $root "infra") "assemble"
    Start-Process -FilePath $python -ArgumentList @("-m", "uvicorn", "app:app", "--port", $assemblePort) `
        -WorkingDirectory $assembleDir
    Write-Host "hiru-assemble on http://localhost:$assemblePort"
} elseif (-not $env:ASSEMBLE__SECRET) {
    Write-Host "hiru-assemble not started: ASSEMBLE__SECRET is not set in .env"
}
