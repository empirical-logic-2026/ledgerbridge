<#
.SYNOPSIS
    Runs docker compose for one LedgerBridge environment (ADR-012).

.EXAMPLE
    ./deploy/stack.ps1 -Env test up -d --build
    ./deploy/stack.ps1 -Env test --profile workers up -d
    ./deploy/stack.ps1 -Env test down
#>
param(
    [ValidateSet('test', 'pilot')]
    [string]$Env = 'test',

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ComposeArgs
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $repoRoot ".env.$Env"
$composeFile = Join-Path $PSScriptRoot 'compose.yaml'

if (-not (Test-Path $envFile)) {
    Write-Error "Missing $envFile. Copy .env.$Env.example to .env.$Env and fill in values."
    exit 1
}

if (-not $ComposeArgs) {
    $ComposeArgs = @('ps')
}

# Read by compose.yaml for the services' env_file.
$previous = $env:LEDGERBRIDGE_ENV_FILE
$env:LEDGERBRIDGE_ENV_FILE = $envFile
try {
    & docker compose -p "ledgerbridge-$Env" --env-file $envFile -f $composeFile @ComposeArgs
    $code = $LASTEXITCODE
}
finally {
    $env:LEDGERBRIDGE_ENV_FILE = $previous
}
exit $code
