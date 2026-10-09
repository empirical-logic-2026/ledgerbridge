<#
.SYNOPSIS
    Day-to-day developer commands for LedgerBridge, built on deploy/stack.ps1.

.DESCRIPTION
    Defaults to the test environment. -Env pilot is for the developer only (never Claude Code).
    Commands that need project settings run inside the api container, so they always use the
    selected environment's env file (.env.test or .env.pilot) via deploy/stack.ps1.

.EXAMPLE
    ./dev.ps1 up
    ./dev.ps1 status
    ./dev.ps1 logs api
    ./dev.ps1 tally-companies
    ./dev.ps1 extract -Company "LedgerBridge Test Co"
    ./dev.ps1 test
    ./dev.ps1 seed-test-data
    ./dev.ps1 down
    ./dev.ps1 up -Env pilot
#>
param(
    [Parameter(Position = 0)]
    [ValidateSet('up', 'down', 'status', 'test', 'logs', 'tally-companies', 'extract', 'seed-test-data', 'help')]
    [string]$Command = 'help',

    # Service name for `logs` (mysql, redis, qdrant, api, worker). Empty = all services.
    [Parameter(Position = 1)]
    [string]$Service = '',

    [ValidateSet('test', 'pilot')]
    [string]$Env = 'test',

    # Company (entity) name in the source, for `extract` and `seed-test-data`.
    [string]$Company = ''
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$stack = Join-Path $root 'deploy\stack.ps1'
$envFile = Join-Path $root ".env.$Env"
$connection = "tally-$Env"

function Invoke-Stack {
    # All Docker calls go through deploy/stack.ps1 (project name, env file, env_file path).
    & $stack -Env $Env @args
    if ($LASTEXITCODE -ne 0) { throw "docker compose failed (exit $LASTEXITCODE)" }
}

function Get-EnvValue([string]$Name, [string]$Default = '') {
    # Reads one non-secret setting from the env file; never prints the file.
    if (-not (Test-Path $envFile)) { return $Default }
    $line = Get-Content $envFile | Where-Object { $_ -match "^$Name=" } | Select-Object -Last 1
    if ($line) { return ($line -replace "^$Name=", '').Trim() }
    return $Default
}

function Assert-EnvFile {
    if (-not (Test-Path $envFile)) {
        throw "Missing .env.$Env. Copy .env.$Env.example to .env.$Env and fill in the passwords."
    }
}

function Assert-PortsFree {
    # Docker's own port forwarders are fine (our containers already running); anything else is a clash.
    $ours = 'com.docker.backend', 'wslrelay', 'vpnkit', 'docker-proxy'
    foreach ($name in 'MYSQL_HOST_PORT', 'REDIS_HOST_PORT', 'QDRANT_HOST_PORT', 'API_HOST_PORT') {
        $port = Get-EnvValue $name
        if (-not $port) { continue }
        $listener = Get-NetTCPConnection -LocalPort ([int]$port) -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if (-not $listener) { continue }
        $owner = (Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue).ProcessName
        if ($owner -and $ours -notcontains $owner) {
            throw "Port $port ($name) is already used by '$owner' (PID $($listener.OwningProcess)). " +
                "Stop that program or change $name in .env.$Env."
        }
    }
}

function Get-RunningServices {
    $services = & $stack -Env $Env ps --status running --services
    if ($LASTEXITCODE -ne 0) { return @() }
    return @($services)
}

function Assert-ApiRunning {
    $running = Get-RunningServices
    if (-not ($running -contains 'api')) { throw "The api container is not running. Start it with: ./dev.ps1 up -Env $Env" }
}

function Get-ApiBase { "http://127.0.0.1:$(Get-EnvValue 'API_HOST_PORT' '8000')" }

function Show-Health {
    $base = Get-ApiBase
    try {
        $ready = Invoke-RestMethod "$base/health/ready" -TimeoutSec 5
        Write-Host "API readiness: $($ready.status) (mysql $($ready.mysql), redis $($ready.redis), qdrant $($ready.qdrant))"
    }
    catch {
        Write-Host "API readiness: not reachable at $base ($($_.Exception.Message))" -ForegroundColor Yellow
    }
}

function Invoke-Uv {
    # uv may only be installed as a Python module on this machine.
    if (Get-Command uv -ErrorAction SilentlyContinue) { & uv @args } else { & python -m uv @args }
    if ($LASTEXITCODE -ne 0) { throw "uv $($args -join ' ') failed (exit $LASTEXITCODE)" }
}

switch ($Command) {
    'up' {
        Assert-EnvFile
        Assert-PortsFree
        Invoke-Stack up -d --build --wait
        # Migrations run as the migrator user in a one-off container; the running api never
        # holds schema-change rights (schema.md 2.1).
        Write-Host "Applying database migrations (one-off migrate container)..."
        Invoke-Stack run --rm migrate
        $base = Get-ApiBase
        Write-Host ""
        Write-Host "LedgerBridge ($Env) is up." -ForegroundColor Green
        Show-Health
        Write-Host "  Dashboard:  $(Get-EnvValue 'FRONTEND_ORIGIN' 'http://localhost:5173')  (start it with: cd frontend; npm run dev)"
        Write-Host "  API health: $base/health/ready"
        Write-Host "  API docs:   $base/docs"
    }
    'down' {
        Assert-EnvFile
        # Keeps volumes (data). To wipe the test database use: ./deploy/stack.ps1 -Env test down -v
        Invoke-Stack down
    }
    'status' {
        Assert-EnvFile
        Invoke-Stack ps
        Show-Health
    }
    'logs' {
        Assert-EnvFile
        if ($Service) { Invoke-Stack logs -f --tail 200 $Service } else { Invoke-Stack logs -f --tail 200 }
    }
    'tally-companies' {
        Assert-EnvFile
        Assert-ApiRunning
        Invoke-Stack exec -T api python -m workers.cli entities --connection $connection --source tally
    }
    'extract' {
        if (-not $Company) { throw 'extract needs -Company "<name>", e.g. ./dev.ps1 extract -Company "LedgerBridge Test Co"' }
        Assert-EnvFile
        Assert-ApiRunning
        Invoke-Stack exec -T api python -m workers.cli extract --connection $connection --source tally --entity $Company
    }
    'seed-test-data' {
        # Writes into Tally (ADR-014): test environment and test company only. The tool itself
        # re-checks APP_ENV, that only one company is loaded and that its name matches exactly.
        if ($Env -ne 'test') { throw 'seed-test-data runs only against the test environment.' }
        Assert-EnvFile
        if (-not $Company) { $Company = 'LedgerBridge Test Co' }
        Push-Location (Join-Path $root 'data-plane')
        try { Invoke-Uv run python -m devtools.tally_seed --company $Company }
        finally { Pop-Location }
    }
    'test' {
        if ($Env -ne 'test') {
            # Integration tests run migrations up and down: never against pilot data.
            throw 'Tests run only against the test environment.'
        }
        Push-Location (Join-Path $root 'data-plane')
        try {
            Invoke-Uv run ruff check .
            Invoke-Uv run ruff format --check .
            Invoke-Uv run python -m pytest -q
            if ((Get-RunningServices) -contains 'mysql') {
                Invoke-Uv run python -m pytest -q -m integration
            }
            else {
                Write-Host 'Skipping integration tests: test stack not running (./dev.ps1 up).' -ForegroundColor Yellow
            }
        }
        finally { Pop-Location }
        Push-Location (Join-Path $root 'frontend')
        try {
            npm run lint
            if ($LASTEXITCODE -ne 0) { throw 'frontend lint failed' }
            npm test -- --run
            if ($LASTEXITCODE -ne 0) { throw 'frontend tests failed' }
        }
        finally { Pop-Location }
        Write-Host 'All checks passed.' -ForegroundColor Green
    }
    default {
        Get-Help $PSCommandPath -Detailed
    }
}
