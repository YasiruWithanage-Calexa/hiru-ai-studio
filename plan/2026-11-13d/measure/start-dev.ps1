# Measurement stack for plan/2026-11-13d (section 6): the API with the traffic trace on. Stops whatever listens on the
# API and function ports first. Logs go to measure/logs/.
#   powershell -File plan\2026-11-13d\measure\start-dev.ps1              # API only, trace to measure/trace.jsonl
#   powershell -File plan\2026-11-13d\measure\start-dev.ps1 -Functions   # also every function, guarded (below)
#   powershell -File plan\2026-11-13d\measure\start-dev.ps1 -Normal      # API + functions from .env as is, no trace
#
# WARNING (2026-11-13): the phase 0 creation walk made real OpenAI calls (~$1.34) with the functions started by an
# earlier version of this script that only removed OPENAI__API_KEY from their environment. A probe started the same way
# saw no key; the cause is not known (IMPLEMENTED.md, phase 0). The person chose no more build walks. -Functions
# therefore also points every function's HTTPS proxy at a dead local port (Supabase and localhost exempt), so no
# request can reach OpenAI whatever key a function finds. Check token_usage after any run that starts a job.
param([switch]$Normal, [switch]$Functions, [string]$Trace = "plan/2026-11-13d/measure/trace.jsonl",
      [string]$Transport = "poll")
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$python = Join-Path $root ".venv\Scripts\python.exe"
$logs = Join-Path $PSScriptRoot "logs"
New-Item -ItemType Directory -Force $logs | Out-Null

$ports = @(8001) + (8201..8215)
foreach ($c in Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in $ports }) {
    try { Stop-Process -Id $c.OwningProcess -Force -ErrorAction Stop } catch {}
}
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*functions_framework*" } |
    ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }
Start-Sleep -Seconds 2

Get-Content (Join-Path $root ".env") | Where-Object { $_ -match '^\s*[A-Z_]+=' } | ForEach-Object {
    $k, $v = $_ -split '=', 2
    $v = $v.Trim()
    if ($v.Length -ge 2 -and ($v[0] -eq '"' -or $v[0] -eq "'") -and $v[-1] -eq $v[0]) { $v = $v.Substring(1, $v.Length - 2) }
    [Environment]::SetEnvironmentVariable($k.Trim(), $v, "Process")
}

if ($Functions -or $Normal) {
    $saved = @{}
    if (-not $Normal) {
        # On Windows an empty value REMOVES the variable; the functions read only the environment, so it is absent.
        [Environment]::SetEnvironmentVariable("OPENAI__API_KEY", $null, "Process")
        $sb = ([Uri]$env:SUPABASE__URL).Host
        foreach ($name in "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY") { $saved[$name] = [Environment]::GetEnvironmentVariable($name, "Process") }
        $env:HTTPS_PROXY = "http://127.0.0.1:9"
        $env:HTTP_PROXY = "http://127.0.0.1:9"
        $env:NO_PROXY = "localhost,127.0.0.1,::1,$sb"
    }
    $services = @(
        @("echo", 8201), @("doc_ingest", 8202), @("script_split", 8203), @("structure_build", 8204),
        @("canon_extract", 8205), @("director_chat", 8206), @("shot_producer", 8207), @("frame_render", 8208),
        @("shot_planner_adam", 8209), @("shot_planner_david", 8210), @("shot_planner_jonathan", 8211),
        @("video_render", 8212), @("zora_chat", 8213), @("sable_chat", 8214), @("shot_planner_raphael", 8215)
    )
    foreach ($f in $services) {
        $src = Join-Path $root "src\services\$($f[0])"
        $env:PYTHONPATH = $src
        Start-Process -FilePath $python -WindowStyle Hidden -WorkingDirectory $src `
            -RedirectStandardOutput (Join-Path $logs "$($f[0]).out.log") -RedirectStandardError (Join-Path $logs "$($f[0]).err.log") `
            -ArgumentList @("-m", "functions_framework", "--target", "handle", "--source", "`"$(Join-Path $src "main.py")`"", "--port", $f[1])
    }
    Remove-Item Env:PYTHONPATH
    foreach ($name in $saved.Keys) { [Environment]::SetEnvironmentVariable($name, $saved[$name], "Process") }
}

$env:LIVE__TRANSPORT = $Transport
if (-not $Normal) {
    $env:DEBUG_TRAFFIC = "true"
    $env:DEBUG_TRAFFIC_LOG = $Trace
}
Start-Process -FilePath $python -WindowStyle Hidden -WorkingDirectory $root `
    -RedirectStandardOutput (Join-Path $logs "api.out.log") -RedirectStandardError (Join-Path $logs "api.err.log") `
    -ArgumentList @("-m", "uvicorn", "api.main:app", "--app-dir", "src", "--env-file", ".env", "--port", "8001")
Write-Host "API on :8001 (trace: $(if ($Normal) { 'off' } else { $Trace })); functions: $(if ($Normal) { 'from .env' } elseif ($Functions) { 'guarded, no key' } else { 'not started' })"
