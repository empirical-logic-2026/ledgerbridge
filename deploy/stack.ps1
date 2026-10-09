<#
.SYNOPSIS
    Runs docker compose for one LedgerBridge environment (ADR-012).

.EXAMPLE
    ./deploy/stack.ps1 -Env test up -d --build
    ./deploy/stack.ps1 -Env test --profile workers up -d
    ./deploy/stack.ps1 -Env test down

.NOTES
    Deliberately a *simple* script (no [Parameter()] / [CmdletBinding()] attributes). An advanced
    script adds PowerShell's common parameters, which swallow docker flags such as -d (-Debug)
    and -v (-Verbose). Everything after -Env is passed to docker compose unchanged via $args.
#>
param(
    [string]$Env = 'test'
)

$ComposeArgs = @($args)
if (@('test', 'pilot') -notcontains $Env) {
    # -Env omitted: the first compose argument was bound to $Env.
    $ComposeArgs = @($Env) + $ComposeArgs
    $Env = 'test'
}

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
    # docker compose writes progress to stderr. Under 'Stop', Windows PowerShell 5.1 turns
    # redirected stderr lines into terminating errors, so rely on the exit code instead.
    $ErrorActionPreference = 'Continue'
    & docker compose -p "ledgerbridge-$Env" --env-file $envFile -f $composeFile @ComposeArgs
    $code = $LASTEXITCODE
}
finally {
    $env:LEDGERBRIDGE_ENV_FILE = $previous
}
exit $code
