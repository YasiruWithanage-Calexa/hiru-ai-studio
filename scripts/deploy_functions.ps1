# Deploy the Cloud Run functions by hand (plan/2026-11-27 D3). Run from the repo root:
#   powershell -File scripts\deploy_functions.ps1                          # every function
#   powershell -File scripts\deploy_functions.ps1 -Only hiru-echo,hiru-frame-render
#   powershell -File scripts\deploy_functions.ps1 -BundleOnly C:\temp\b    # build the bundles, deploy nothing
# The list of functions (source, memory, timeout) is the one in .github/workflows/deploy-functions.yml, and each bundle
# is built the same way: the service folder + `contracts` + `hiru_ai` without its tests and sources.
# Settings come from infra/env/<environment>.env (the API gets the same list); secrets are bound from Secret Manager.
param(
    [string]$Environment = "staging",
    [string[]]$Only = @(),
    [string]$Outputs = "",
    [string]$BundleOnly = "",
    [switch]$DryRun
)
. (Join-Path $PSScriptRoot "deploy_common.ps1")

# These two run the hiru_ai engine wherever they run (scripts/start-functions.ps1 says why); the rest use the default.
$GraphEngine = @("hiru-shot-producer", "hiru-frame-render")
$MaxInstances = 10 # = the queue's max_concurrent_dispatches (infra/terraform/main.tf)

$workflow = Get-Content -Raw -Encoding UTF8 (Join-Path $RepoRoot ".github\workflows\deploy-functions.yml")
if ($workflow -notmatch "(?s)ALL='(\[.*?\])'") { throw "The function list was not found in deploy-functions.yml" }
# (`ForEach-Object { $_ }`: 5.1's ConvertFrom-Json hands a JSON array on as one object)
$functions = @($Matches[1] | ConvertFrom-Json | ForEach-Object { $_ })

if ($Only.Count) {
    $Only = @($Only | ForEach-Object { $_ -split "," } | Where-Object { $_ })
    $unknown = @($Only | Where-Object { $_ -notin $functions.name })
    if ($unknown.Count) { throw "No such function: $($unknown -join ', '). Known: $($functions.name -join ', ')" }
    $functions = @($functions | Where-Object { $_.name -in $Only })
}

# robocopy, not Copy-Item: some paths in the AI package are longer than Windows PowerShell 5.1 can open.
function Copy-Tree {
    param([string]$From, [string]$To, [string[]]$SkipFolders = @(), [string[]]$SkipFiles = @())
    $arguments = @($From, $To, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/NP", "/XD", "__pycache__") + $SkipFolders +
        @("/XF", "*.pyc") + $SkipFiles
    & robocopy @arguments | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy $From failed with exit code $LASTEXITCODE" } # 0-7 are successes
    $global:LASTEXITCODE = 0
}

function New-Bundle {
    param($Function, [string]$Target)
    if (Test-Path $Target) { Remove-Item -Recurse -Force $Target }
    New-Item -ItemType Directory -Force $Target | Out-Null
    Copy-Tree (Join-Path $RepoRoot ($Function.src -replace "/", "\")) $Target
    Copy-Tree (Join-Path $RepoRoot "src\libs\contracts") (Join-Path $Target "contracts")
    if ($Function.ai) {
        # without what only developers use: each part's tests, examples and evals, and the knowledge bases' sources
        Copy-Tree (Join-Path $RepoRoot "src\libs\hiru_ai") (Join-Path $Target "hiru_ai") `
            -SkipFolders @("tests", "examples", "evals", "sources") -SkipFiles @("conftest.py")
    }
    # Folders left empty (a deleted part's old __pycache__ on a developer's machine) would reach the function as parts
    # with no manifest, which the registry reports as errors. Deepest first, so emptied parents go too.
    Get-ChildItem -Recurse -Directory $Target | Sort-Object { $_.FullName.Length } -Descending |
        Where-Object { -not (Get-ChildItem -Force -LiteralPath $_.FullName) } |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName }
}

if ($BundleOnly) {
    foreach ($f in $functions) {
        New-Bundle $f (Join-Path $BundleOnly $f.name)
        Write-Host "bundled $($f.name)"
    }
    return
}

$out = Get-DeployOutputs $Outputs
$settings = Get-DeploySettings $Environment
Assert-MediaSettings $settings $out
$work = Join-Path ([System.IO.Path]::GetTempPath()) "hiru-deploy-functions"
$failed = @()

foreach ($f in $functions) {
    Write-Host "== $($f.name)"
    $bundle = Join-Path $work $f.name
    New-Bundle $f $bundle

    $vars = [ordered]@{}
    foreach ($key in $settings.Keys) { $vars[$key] = $settings[$key] }
    $vars["SUPABASE__URL"] = $out.supabase_url
    $vars["API__INTERNAL_URL"] = $out.api_url
    $vars["FILES__CACHE_MAX_GB"] = "0" # the disk of a function is memory (plan F5)
    if ($f.name -in $GraphEngine) { $vars["AI_ENGINE"] = "graph" }

    $p = $out.secret_prefix
    $secrets = @(
        "SUPABASE__SERVICE_ROLE_KEY=$p-supabase-service-role-key:latest",
        "OPENAI__API_KEY=$p-openai-api-key:latest",
        "API__INTERNAL_SECRET=$p-api-internal-secret:latest",
        "SUPABASE__DB_URL=$p-supabase-db-url:latest")
    if ($f.assemble) {
        # Only the function that calls assemble gets its address, its secret and the video provider's key.
        $vars["ASSEMBLE__URL"] = $out.assemble_url
        $secrets += "ASSEMBLE__SECRET=$p-assemble-secret:latest"
        $secrets += "GOOGLE__API_KEY=$p-google-api-key:latest"
    }

    # A file, not --set-env-vars: no value has to survive command line quoting.
    $envFile = Join-Path $work "$($f.name).env.yaml"
    Write-UnixFile $envFile @($vars.Keys | ForEach-Object { "${_}: '$($vars[$_] -replace "'", "''")'" })

    $arguments = @(
        "functions", "deploy", $f.name, "--gen2", "--runtime", "python312",
        "--project", $out.project_id, "--region", $out.region,
        "--source", $bundle, "--entry-point", "handle", "--trigger-http",
        "--no-allow-unauthenticated", "--ingress-settings", "internal-only",
        "--service-account", $out.functions_sa,
        # the address alone: the service adds `projects/<id>/serviceAccounts/` itself (a full name was doubled)
        "--build-service-account", $out.build_sa,
        "--memory", $f.memory, "--timeout", "$($f.timeout)s", "--max-instances", "$MaxInstances",
        "--env-vars-file", $envFile, "--set-secrets", ($secrets -join ","), "--quiet")
    try { Invoke-Tool gcloud $arguments -DryRun:$DryRun }
    catch { Write-Warning "$($f.name): $_"; $failed += $f.name }
}

if ($failed.Count) { throw "Not deployed: $($failed -join ', ')" }
Write-Host "Done: $($functions.Count) function(s)."
