# Give each Secret Manager secret of an environment its value (plan/2026-11-27, phase 2). Run from the repo root,
# after the targeted Terraform apply that creates the (empty) secrets:
#   powershell -File scripts\load_secrets.ps1 -DryRun     # say what would be set, from where
#   powershell -File scripts\load_secrets.ps1
# Provider keys come from .env. The two secrets that only protect our own services from each other
# (api-internal-secret, assemble-secret) are made new and random: the cloud never uses a developer's values.
# A secret that already has a value is left alone (-Replace adds a new version). No value is ever printed or put on a
# command line; each passes through a temporary file that is removed at once.
param(
    [string]$Environment = "staging",
    [string]$EnvFile = "",
    [switch]$Replace,
    [switch]$DryRun
)
. (Join-Path $PSScriptRoot "deploy_common.ps1")

if (-not $EnvFile) { $EnvFile = Join-Path $RepoRoot ".env" }
$tfvars = Join-Path $RepoRoot "infra\terraform\$Environment.tfvars"
if (-not (Test-Path $tfvars)) { throw "No $tfvars (see the .tfvars.example beside it)" }
$project = (Select-String -Path $tfvars -Pattern '^\s*project_id\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
$prefix = "hiru-$Environment"

$local = @{}
foreach ($line in Get-Content -Encoding UTF8 $EnvFile) {
    if ($line -notmatch '^\s*([A-Z][A-Z0-9_]*)\s*=(.*)$') { continue }
    $name = $Matches[1]
    $value = $Matches[2].Trim()
    if ($value.Length -ge 2 -and ($value[0] -eq '"' -or $value[0] -eq "'") -and $value[-1] -eq $value[0]) {
        $value = $value.Substring(1, $value.Length - 2) # KEY="value" as dotenv reads it
    }
    $local[$name] = $value
}

function New-RandomSecret {
    $bytes = New-Object byte[] 32
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) } finally { $generator.Dispose() }
    return [Convert]::ToBase64String($bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

# secret name (without the prefix) = the .env variable it comes from; "" = made new
$wanted = [ordered]@{
    "supabase-service-role-key" = "SUPABASE__SERVICE_ROLE_KEY"
    "supabase-db-url"           = "SUPABASE__DB_URL"
    "openai-api-key"            = "OPENAI__API_KEY"
    "google-api-key"            = "GOOGLE__API_KEY"
    "api-internal-secret"       = ""
    "assemble-secret"           = ""
}

# Everything is checked before anything is written.
$missing = @($wanted.Values | Where-Object { $_ -and -not $local[$_] })
if ($missing.Count) { throw "No value in ${EnvFile}: $($missing -join ', ')" }

foreach ($short in $wanted.Keys) {
    $secret = "$prefix-$short"
    $source = $wanted[$short]
    $from = if ($source) { "$source in .env" } else { "a new random value" }
    if ($DryRun) { Write-Host "  [dry run] $secret <- $from"; continue }

    # any version counts (a filter on `state` makes gcloud warn about every secret that has none yet)
    $has = & gcloud secrets versions list $secret --project $project --limit 1 --format "value(name)" --quiet
    if ($LASTEXITCODE -ne 0) { throw "The secret $secret cannot be read: has Terraform created it?" }
    if ($has -and -not $Replace) { Write-Host "$secret already has a value: left alone"; continue }

    $value = if ($source) { $local[$source] } else { New-RandomSecret }
    $file = [System.IO.Path]::GetTempFileName()
    try {
        # exactly the value's bytes: no byte order mark, no line end
        [System.IO.File]::WriteAllText($file, $value, (New-Object System.Text.UTF8Encoding($false)))
        Invoke-Tool gcloud @("secrets", "versions", "add", $secret, "--project", $project, "--data-file", $file, "--quiet")
    } finally {
        Remove-Item -Force -LiteralPath $file
    }
    Write-Host "$secret <- $from"
}
