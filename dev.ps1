<#
.SYNOPSIS
    Day-to-day developer commands for LedgerBridge, built on deploy/stack.ps1.

.DESCRIPTION
    Defaults to the test environment. -Env pilot is for the developer only (never Claude Code).
    Commands that need project settings run inside the api container, so they always use the
    selected environment's env file (.env.test or .env.pilot) via deploy/stack.ps1.

    Where it fits: the front door for people. Each command checks its arguments and the
    environment, then runs `python -m workers.cli <command>` in the api container (or a
    docker compose command, or a throwaway tool container), all through deploy/stack.ps1.

.EXAMPLE
    ./dev.ps1 up                          (pilot: backs up the databases first)
    ./dev.ps1 backup                      (a full copy of the databases to backups/<env>/)
    ./dev.ps1 status
    ./dev.ps1 report [-Details]                 (health report: verdict, problems, next steps; saved under reports/)
    ./dev.ps1 logs api
    ./dev.ps1 tally-companies
    ./dev.ps1 extract -Company "LedgerBridge Test Co"
    ./dev.ps1 sync -Company "LedgerBridge Test Co"
    ./dev.ps1 sync full -Company "LedgerBridge Test Co"
    ./dev.ps1 sync deletions
    ./dev.ps1 validate
    ./dev.ps1 transform retry                   (transform failed records again; no Tally)
    ./dev.ps1 transform rebuild                 (transform every stored record again; no Tally)
    ./dev.ps1 transform explain [-CheckSource]  (why references didn't resolve; counts only)
    ./dev.ps1 validate analyse                  (test explanations for validation mismatches)
    ./dev.ps1 validate compare-ledger -Ledger 88 [-From 2020-04-01] [-To 2021-04-01]
    ./dev.ps1 statements [-From 2026-04-01]    (stock values and statements at every month end; compared with the source)
                                                (a ledger's vouchers in Tally against ours; details to reports/<env>/private/)
    ./dev.ps1 fields
    ./dev.ps1 promote-field -FieldId 12 -Code SALESMAN -Name "Salesman"
    ./dev.ps1 test
    ./dev.ps1 diagrams                          (regenerate docs/diagrams and the schema reference from the models, render SVG/PNG)
    ./dev.ps1 docs-export                       (Word and PDF copies of the rulebook, schema reference and history in docs/export)
    ./dev.ps1 seed-test-data
    ./dev.ps1 seed-test-data create-only
    ./dev.ps1 seed-test-data integrated-off     (or integrated-on: the test company's setting)
    ./dev.ps1 down

    Pilot (developer only; see docs/pilot-runbook.md):
    ./dev.ps1 init-env -Env pilot
    ./dev.ps1 up -Env pilot
    ./dev.ps1 connect -Env pilot -Origin backup -All
    ./dev.ps1 entity-check -Env pilot
    ./dev.ps1 sync full -Env pilot              (re-run it to continue after an interruption)
    ./dev.ps1 sync full -Env pilot -Restart     (start over)
    ./dev.ps1 sync full -Env pilot -From 2024-03-01   (fetch again from a date)
    ./dev.ps1 sync watch -Env pilot             (follow a running sync again)
    ./dev.ps1 sync abandon -Env pilot           (mark runs whose process is gone interrupted)
    ./dev.ps1 transform retry -Env pilot        (failed records again with the current code)
    ./dev.ps1 transform rebuild -Env pilot      (every stored record again with the current code)
    ./dev.ps1 transform explain -Env pilot      (why references didn't resolve; -CheckSource asks Tally)
    ./dev.ps1 validate analyse -Env pilot       (why validation mismatches; reads Tally's figures)
    ./dev.ps1 statements -Env pilot             (stock values and statements at every month end; counts only)
    ./dev.ps1 summary -Env pilot
    ./dev.ps1 report -Env pilot [-Details]      (saved as reports/pilot/report-<date>.md, safe to share)
    ./dev.ps1 reset -Env pilot
#>
param(
    [Parameter(Position = 0)]
    [ValidateSet('init-env', 'up', 'backup', 'down', 'reset', 'entity-check', 'status', 'summary', 'report', 'test', 'logs', 'tally-companies', 'connect', 'extract', 'sync', 'validate', 'transform', 'statements', 'fields', 'promote-field', 'seed-test-data', 'diagrams', 'docs-export', 'help')]
    [string]$Command = 'help',

    # Service name for `logs` (mysql, redis, qdrant, api, worker). Empty = all services.
    [Parameter(Position = 1)]
    [string]$Service = '',

    [ValidateSet('test', 'pilot')]
    [string]$Env = 'test',

    # Company (entity) names in the source: one for `extract` and `seed-test-data`; one or
    # more (comma-separated) for `connect`, `sync` and `validate`.
    [string[]]$Company = @(),

    # For `connect`: the origin tag of the connection's data (IMP-004).
    [ValidateSet('live', 'backup')]
    [string]$Origin = 'live',

    # For `connect`: new connections start paused (no scheduled syncs; manual syncs work).
    # -Activate lets the worker sync it on its schedule; -Paused stops that again.
    [switch]$Activate,
    [switch]$Paused,

    # For `connect`: every company currently loaded in Tally, instead of -Company names.
    [switch]$All,

    # For `connect`: seconds one Tally request may take, stored on the connection. Without it
    # a connection uses TALLY_TIMEOUT_SEC from the env file.
    [int]$TimeoutSec = 0,

    # For `connect`: pause in seconds between Tally requests during a sync (eases the load).
    [int]$PauseSec = -1,

    # For `connect`: whether Tally runs in Educational mode (reliable balances on the 1st,
    # 2nd and 31st only; validation and analysis then use those dates). auto = ask Tally.
    [ValidateSet('', 'auto', 'yes', 'no')]
    [string]$Educational = '',

    # For `connect`: whether Tally answers requests for part of a month (auto = check once).
    [ValidateSet('', 'auto', 'supported', 'unsupported')]
    [string]$PartMonth = '',

    # For `sync full`: fetch again every chunk of an interrupted full sync from this date
    # (YYYY-MM-DD), e.g. a damaged range; earlier completed chunks are kept.
    # For `validate compare-ledger`: compare from this date (default: the books' beginning).
    [string]$From = '',

    # For `validate compare-ledger`: compare up to this date (default: today).
    [string]$To = '',

    # For `validate compare-ledger`: the ledger's id (as reports and `validate analyse`
    # name ledgers).
    [int]$Ledger = 0,

    # For `sync full`: ignore an interrupted full sync's progress and fetch everything again.
    [switch]$Restart,

    # For `validate`: skip the source's controls (voucher counts, stock, bills, year ends).
    [switch]$Quick,

    # For `transform retry`: don't validate afterwards (validation reads Tally's figures).
    [switch]$NoValidate,

    # For `transform explain`: also ask Tally (read-only) what it lists now.
    [switch]$CheckSource,

    # For `report`: expand every section (failure breakdowns, notes, fixed checks).
    [switch]$Details,

    # Plain output without colours (also when NO_COLOR is set or the output is redirected).
    [switch]$NoColor,

    # For `promote-field`: the catalogued field's id (from `fields`), and the dimension's
    # code and name.
    [int]$FieldId = 0,
    [string]$Code = '',
    [string]$Name = '',

    # For `reset`: required to reset the test environment; pilot always asks.
    [switch]$Force,

    # For `reset`: the typed confirmation, for scripted use. Normally you're asked to type it.
    [string]$Confirmation = ''
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$stack = Join-Path (Join-Path $PSScriptRoot 'deploy') 'stack.ps1'
# Tests only (tests/test_dev_script_args.py): a stand-in for deploy/stack.ps1 that records
# the docker compose arguments each command builds instead of running Docker.
if ($env:LEDGERBRIDGE_DEV_STACK) { $stack = $env:LEDGERBRIDGE_DEV_STACK }
$envFile = Join-Path $root ".env.$Env"
$connection = "tally-$Env"

function Get-ColorArgs {
    # Colours for status words (green / yellow / red), only when this terminal shows them:
    # not with -NoColor or NO_COLOR, not when the output is redirected to a file or pipe.
    # The command inside the container can't tell (its output is a pipe), so it is told.
    if ($NoColor -or $env:NO_COLOR -or [Console]::IsOutputRedirected) { return @() }
    try { if (-not $Host.UI.SupportsVirtualTerminal) { return @() } } catch { return @() }
    return @('-e', 'LB_COLOR=1')
}

function Add-ColorArgs([object[]]$Arguments) {
    # `exec -T api ...` becomes `exec -T -e LB_COLOR=1 api ...` when colours are on.
    # PowerShell unwraps a one-element array returned by a function
    # into a plain string, and splatting a string passes its characters (`ps` became `p s`).
    # Callers therefore always wrap the call in @(), which collects it back into an array.
    if ($Arguments.Count -ge 2 -and $Arguments[0] -eq 'exec' -and $Arguments[1] -eq '-T') {
        return @('exec', '-T') + @(Get-ColorArgs) + @($Arguments | Select-Object -Skip 2)
    }
    return $Arguments
}

function Invoke-Stack {
    # All Docker calls go through deploy/stack.ps1 (project name, env file, env_file path).
    $stackArgs = @(Add-ColorArgs $args)
    & $stack -Env $Env @stackArgs
    if ($LASTEXITCODE -ne 0) { throw "docker compose failed (exit $LASTEXITCODE)" }
}

function Invoke-Checked {
    # For workers.cli commands whose exit codes mean "ran, but": 1 = checks or the sync
    # failed, 2 = refused or not found, 3 = a sync is already running. Reported plainly
    # instead of as a Docker failure.
    $stackArgs = @(Add-ColorArgs $args)
    & $stack -Env $Env @stackArgs
    switch ($LASTEXITCODE) {
        0 { }
        1 { Write-Host "Finished with problems: see the FAILED / error lines above, or: ./dev.ps1 report -Env $Env" -ForegroundColor Yellow }
        2 { Write-Host 'Refused or not found: see the message above.' -ForegroundColor Yellow }
        3 { Write-Host "A sync of this connection is already running (the worker may have started it) [LB-SYNC-008]. Wait, then: ./dev.ps1 sync watch -Env $Env" -ForegroundColor Yellow }
        default { throw "docker compose failed (exit $LASTEXITCODE)" }
    }
}

function Get-EnvValue([string]$Name, [string]$Default = '') {
    # Reads one non-secret setting from the env file; never prints the file.
    if (-not (Test-Path $envFile)) { return $Default }
    $line = Get-Content $envFile | Where-Object { $_ -match "^$Name=" } | Select-Object -Last 1
    if ($line) { return ($line -replace "^$Name=", '').Trim() }
    return $Default
}

function Assert-Step([string]$Command, [string[]]$Steps) {
    # A word after the command must be one of its steps: an unknown or misspelt one (or one
    # from a newer version of this script) stops here, instead of running the plain command
    # as if no step had been given (pilot, 2026-10-24: `validate fx-rules` ran a validation).
    if ($Service -and $Service -notin $Steps) {
        $known = if ($Steps) { $Steps -join ', ' } else { 'none' }
        throw "Unknown step '$Service' for '$Command' (its steps: $known); nothing was run. After updating the code, check the checked-out branch has it (git log)."
    }
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

function Backup-Database {
    # A full copy of the four databases (ADR-016), taken inside the mysql container so the
    # root password never appears on this machine's command line, then copied out to
    # backups/<env>/ (git-ignored: it holds the environment's data). Restore: docs/pilot-runbook.md.
    $folder = Join-Path (Join-Path $root 'backups') $Env
    New-Item -ItemType Directory -Force -Path $folder | Out-Null
    $file = "ledgerbridge-$Env-$(Get-Date -Format 'yyyyMMdd-HHmmss').sql.gz"
    $inside = '/tmp/ledgerbridge-backup.sql.gz'
    Write-Host "Backing up the $Env databases before anything changes them..."
    $dump = 'set -o pipefail; MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump -uroot --single-transaction ' +
        '--routines --triggers --set-gtid-purged=OFF --databases ledgerbridge_source ' +
        "ledgerbridge_accounting ledgerbridge_reporting ledgerbridge_system | gzip > $inside"
    Invoke-Stack exec -T mysql bash -c $dump
    Invoke-Stack cp "mysql:$inside" (Join-Path $folder $file)
    Invoke-Stack exec -T mysql rm -f $inside
    $saved = Get-Item (Join-Path $folder $file)
    Write-Host ("Backup saved: {0} ({1:N1} MB)" -f $saved.FullName, ($saved.Length / 1MB)) -ForegroundColor Green
}

function Assert-CodeCurrent {
    # The running stack's code (its image's git commit, stamped at build: ADR-045) against
    # the checked-out commit. A stack not rebuilt after an update runs the older code (pilot
    # 2026-10-24: validate and report ran an image from before the fix). Pilot: stop; test:
    # warn. Without git the check is skipped.
    $code = & git -C $root rev-parse --short=12 HEAD 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $code) { return }
    $code = "$code".Trim()
    $found = Invoke-StackCaptured @('exec', '-T', 'api', 'printenv', 'LEDGERBRIDGE_COMMIT')
    $running = if ($found.Code -eq 0 -and $found.Output) { "$($found.Output[0])".Trim() } else { 'unknown' }
    if ($running -eq $code) { return }
    $message = "The $Env stack runs code $running but the checked-out code is ${code}: run ./dev.ps1 up -Env $Env"
    if ($Env -eq 'pilot') { throw $message }
    Write-Warning $message
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

function Start-Followed([string]$Kind, [string]$Job, [object[]]$Arguments) {
    # Starts a workers.cli job in the background inside the api container, then follows its
    # output here. Closing this window never stops the job (ADR-024).
    Invoke-Stack exec -d api @Arguments
    Write-Host "Started $Kind job $Job in the background. Following it; closing this window doesn't stop it (follow again with: ./dev.ps1 sync watch -Env $Env)."
    Invoke-Checked exec -T api python -m workers.cli watch --connection $connection --job $Job
}

function Invoke-StackCaptured([object[]]$Arguments) {
    # Runs a command in the stack without printing it: its output lines (read as UTF-8) and
    # exit code, for output that is saved to a file or split before it is shown.
    $encoding = [Console]::OutputEncoding
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
    try {
        $ErrorActionPreference = 'Continue'
        $output = @(& $stack -Env $Env @Arguments)
        $code = $LASTEXITCODE
        $ErrorActionPreference = 'Stop'
    }
    finally { [Console]::OutputEncoding = $encoding }
    return @{ Output = $output; Code = $code }
}

function Save-Utf8([string]$Path, [object[]]$Lines) {
    # The lines joined by line feeds, as UTF-8 without a byte-order mark.
    [System.IO.File]::WriteAllText($Path, (($Lines -join "`n") + "`n"), (New-Object System.Text.UTF8Encoding $false))
}

function Invoke-ToolContainer([object[]]$Arguments, [string]$What) {
    # `docker run --rm ...` of a tool image (mermaid-cli, pandoc). The tools write notices to
    # stderr; under 'Stop', Windows PowerShell 5.1 turns those into errors, so rely on the
    # exit code instead (as deploy/stack.ps1 does).
    $ErrorActionPreference = 'Continue'
    $output = & docker @Arguments 2>&1
    $code = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($code -ne 0) {
        $output | Select-Object -Last 5 | ForEach-Object { Write-Host "  $_" }
        throw "$What failed (exit $code)"
    }
}

function Invoke-Uv {
    # uv may only be installed as a Python module. `python` on PATH can be the Windows Store
    # alias, so prefer the Python install manager's copy when it exists.
    $localPython = Join-Path (Join-Path (Join-Path $env:LOCALAPPDATA 'Python') 'bin') 'python.exe'
    if (Get-Command uv -ErrorAction SilentlyContinue) { & uv @args }
    elseif (Test-Path $localPython) { & $localPython -m uv @args }
    else { & python -m uv @args }
    if ($LASTEXITCODE -ne 0) { throw "uv $($args -join ' ') failed (exit $LASTEXITCODE)" }
}

switch ($Command) {
    'init-env' {
        # Creates .env.<Env> from its example with strong random MySQL passwords (never
        # printed). Refuses if the file exists.
        & (Join-Path (Join-Path $PSScriptRoot 'deploy') 'new-env.ps1') -Env $Env
    }
    'connect' {
        # Creates or updates this environment's connection: origin and the exact companies.
        # Prints counts only outside the test environment.
        if (-not $Company -and -not $All) { throw 'connect needs -All, or -Company "<name>","<name>" (exact names as in the source).' }
        if ($Company -and $All) { throw 'Use -All or -Company, not both.' }
        Assert-EnvFile
        Assert-ApiRunning
        $connectArgs = @('python', '-m', 'workers.cli', 'connect', '--connection', $connection, '--source', 'tally', '--origin', $Origin)
        foreach ($name in $Company) { $connectArgs += @('--entity', $name) }
        if ($All) { $connectArgs += '--all' }
        if ($TimeoutSec -gt 0) { $connectArgs += @('--timeout-sec', "$TimeoutSec") }
        if ($PauseSec -ge 0) { $connectArgs += @('--pause-sec', "$PauseSec") }
        if ($PartMonth) { $connectArgs += @('--part-month', $PartMonth) }
        if ($Educational) { $connectArgs += @('--educational', $Educational) }
        if ($Activate -and $Paused) { throw 'Use -Activate or -Paused, not both.' }
        if ($Activate) { $connectArgs += '--activate' }
        if ($Paused) { $connectArgs += '--pause' }
        Invoke-Checked exec -T api @connectArgs
    }
    'reset' {
        # Deletes this environment's data: stops its stack and removes only its own Docker
        # volumes (MySQL, Redis, Qdrant). Keeps .env.<Env>. Needs a typed confirmation.
        if ($Env -eq 'test' -and -not $Force) {
            throw 'reset deletes the test database too: add -Force to reset the test environment.'
        }
        Assert-EnvFile
        $project = "ledgerbridge-$Env"
        $volumes = @(& docker volume ls --quiet --filter "label=com.docker.compose.project=$project")
        Write-Host "This stops '$project' and deletes its data volumes:"
        if ($volumes) { $volumes | ForEach-Object { Write-Host "  $_" } } else { Write-Host '  (none found)' }
        Write-Host ".env.$Env is kept, so the next 'up' recreates the databases with the same passwords."
        $expected = "delete $Env"
        $answer = if ($Confirmation) { $Confirmation } else { Read-Host "Type '$expected' to continue" }
        if ($answer -cne $expected) {
            Write-Host 'Not confirmed: nothing was deleted.' -ForegroundColor Yellow
            exit 2
        }
        Invoke-Stack down --volumes --remove-orphans
        $left = @(& docker volume ls --quiet --filter "label=com.docker.compose.project=$project")
        if ($left) { throw "Volumes still present: $($left -join ', ')" }
        Write-Host "Deleted the $Env data. Start again with: ./dev.ps1 up -Env $Env" -ForegroundColor Green
    }
    'entity-check' {
        # Read-only diagnostic: are the connection's companies in Tally, and if not, how do the
        # names differ (kinds only, never names). Also selects each company once, the way a
        # sync does, and checks whether Tally then lists the names differently.
        Assert-EnvFile
        Assert-ApiRunning
        Invoke-Checked exec -T api python -m workers.cli entity-check --connection $connection --source tally
    }
    'summary' {
        # Counts and pass/fail per connection and company; no names or amounts (safe to share).
        Assert-EnvFile
        Assert-ApiRunning
        Invoke-Stack exec -T api python -m workers.cli summary
    }
    'report' {
        # One health report: overall verdict, connection, data loaded, work in progress (with
        # the resume command), validation per company (compared with the previous run),
        # warnings, and each problem's meaning, likely cause and next step. Reads only the
        # database. Counts, dates and codes only (never names, values or amounts), so the
        # Markdown copy saved under reports/<env>/ (git-ignored) can be shared as it is.
        Assert-EnvFile
        Assert-ApiRunning
        Assert-CodeCurrent  # the stack runs the checked-out code (ADR-045)
        $reportArgs = @('python', '-m', 'workers.cli', 'report')
        foreach ($name in $Company) { $reportArgs += @('--entity', $name) }
        $folder = Join-Path (Join-Path $root 'reports') $Env
        New-Item -ItemType Directory -Force -Path $folder | Out-Null
        $file = Join-Path $folder ('report-{0:yyyy-MM-dd-HHmmss}.md' -f (Get-Date))
        # The full report (with details) as Markdown, read as UTF-8 and saved without a BOM.
        $markdown = Invoke-StackCaptured (@('exec', '-T', 'api') + $reportArgs + @('--format', 'markdown'))
        if ($markdown.Code -gt 1) { throw "The report failed (exit $($markdown.Code)): see the message above." }
        Save-Utf8 $file $markdown.Output
        if ($Details) { $reportArgs += '--details' }
        $stackArgs = @(Add-ColorArgs (@('exec', '-T', 'api') + $reportArgs))
        & $stack -Env $Env @stackArgs
        if ($LASTEXITCODE -gt 1) { throw "The report failed (exit $LASTEXITCODE)." }
        Write-Host ''
        Write-Host "Saved (Markdown, no names or amounts): $file"
    }
    'up' {
        Assert-EnvFile
        Assert-PortsFree
        Invoke-Stack up -d --build --wait
        # Pilot: a full backup before migrations can change anything (developer, 2026-10-24).
        # A failed backup stops here, before migrating.
        if ($Env -eq 'pilot') { Backup-Database }
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
    'backup' {
        # A full copy of the environment's four databases to backups/<env>/ (git-ignored).
        # `up -Env pilot` takes one itself before applying migrations.
        Assert-EnvFile
        Backup-Database
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
        if ((Get-RunningServices) -contains 'api') {
            Write-Host ""
            Write-Host "Syncs (the worker runs due syncs automatically):"
            Invoke-Stack exec -T api python -m workers.cli status
        }
    }
    'sync' {
        # Fetch changes from the source and transform them (M3). -Company limits it to one
        # company; without it the connection's remembered companies (or all loaded) sync.
        # The sync runs in the background inside the api container and writes its output to
        # the database; this window just follows it (ADR-024). Closing the window or Ctrl+C
        # never stops the sync: `sync watch` follows it again, `sync abandon` recovers runs
        # whose process is gone.
        Assert-Step 'sync' @('full', 'deletions', 'watch', 'abandon')
        Assert-EnvFile
        Assert-ApiRunning
        Assert-CodeCurrent  # the stack runs the checked-out code (ADR-045)
        if ($Service -eq 'watch') {
            Invoke-Checked exec -T api python -m workers.cli watch --connection $connection
            return
        }
        if ($Service -eq 'abandon') {
            $expected = 'abandon'
            $answer = if ($Confirmation) { $Confirmation } else { Read-Host "Mark this connection's running sync runs as interrupted? Type '$expected' to continue" }
            if ($answer -cne $expected) { Write-Host 'Not confirmed: nothing changed.' -ForegroundColor Yellow; exit 2 }
            $abandonArgs = @('python', '-m', 'workers.cli', 'abandon', '--connection', $connection, '--yes')
            if ($Force) { $abandonArgs += '--force' }
            Invoke-Checked exec -T api @abandonArgs
            return
        }
        # `sync full` also runs a deletion check; `sync deletions` runs only the deletion check
        # (the worker runs it on its own schedule, hourly by default).
        $mode = if ($Service -eq 'deletions') { 'check-deletions' } else { 'sync' }
        $syncArgs = @('python', '-m', 'workers.cli', $mode, '--connection', $connection, '--source', 'tally')
        foreach ($name in $Company) { $syncArgs += @('--entity', $name) }
        if ($Service -eq 'full') { $syncArgs += @('--full', '--check-deletions') }
        if ($Restart) {
            if ($Service -ne 'full') { throw '-Restart only applies to: sync full -Restart' }
            $syncArgs += '--restart'
        }
        if ($From) {
            if ($Service -ne 'full') { throw '-From only applies to: sync full -From YYYY-MM-DD' }
            $syncArgs += @('--refetch-from', $From)
        }
        $job = [guid]::NewGuid().ToString()
        $syncArgs += @('--job', $job)
        Start-Followed 'sync' $job $syncArgs
    }
    'statements' {
        # Stores the source's stock values and statements (Trial Balance, Profit & Loss,
        # Balance Sheet) at every month end and year end, builds ours and compares them line
        # by line (ADR-040). Reads Tally's figures (read-only), in the background like a
        # sync, followed here. Counts and statement names only. -From starts at a date.
        Assert-Step 'statements' @()
        Assert-EnvFile
        Assert-ApiRunning
        Assert-CodeCurrent  # the stack runs the checked-out code (ADR-045)
        $job = [guid]::NewGuid().ToString()
        $statementArgs = @('python', '-m', 'workers.cli', 'statements', '--connection', $connection, '--job', $job)
        foreach ($name in $Company) { $statementArgs += @('--entity', $name) }
        if ($From) { $statementArgs += @('--from', $From) }
        Start-Followed 'statements' $job $statementArgs
    }
    'validate' {
        # Validation as of today (M4): voucher balance, trial balance and closing balances
        # against the source. Prints counts, check codes and pass/fail only. Syncs validate
        # on their own; this runs it on demand.
        Assert-Step 'validate' @('fx-rules', 'compare-ledger', 'analyse')
        Assert-EnvFile
        Assert-ApiRunning
        Assert-CodeCurrent  # the stack runs the checked-out code (ADR-045)
        if ($Service -eq 'fx-rules') {
            # Which revaluation rule Tally's statements follow (ADR-043): counts per candidate
            # rule over the dates `statements` stored. Reads the groups' netting setting only
            # (read-only); in the background like a sync, followed here. Counts only.
            $job = [guid]::NewGuid().ToString()
            $fxArgs = @('python', '-m', 'workers.cli', 'fx-rules', '--connection', $connection, '--job', $job)
            foreach ($name in $Company) { $fxArgs += @('--entity', $name) }
            Start-Followed 'fx-rules' $job $fxArgs
            return
        }
        if ($Service -eq 'compare-ledger') {
            # One ledger's vouchers in Tally (read-only) against ours, voucher by voucher.
            # Printed: counts by voucher type and month, kinds only. The details (dates,
            # voucher numbers, both amounts) go to a local file under reports/<env>/private/
            # (git-ignored), for you to check in Tally: only its path is printed.
            if ($Ledger -le 0) { throw 'Usage: ./dev.ps1 validate compare-ledger -Ledger <id> [-From YYYY-MM-DD] [-To YYYY-MM-DD]' }
            $compareArgs = @('python', '-m', 'workers.cli', 'compare-ledger', '--connection', $connection, '--ledger', "$Ledger", '--private')
            if ($From) { $compareArgs += @('--from', $From) }
            if ($To) { $compareArgs += @('--to', $To) }
            $result = Invoke-StackCaptured (@('exec', '-T', 'api') + $compareArgs)
            $marker = "PRIVATE`t"
            $private = @($result.Output | Where-Object { "$_".StartsWith($marker) } | ForEach-Object { "$_".Substring($marker.Length) })
            $result.Output | Where-Object { -not "$_".StartsWith($marker) } | ForEach-Object { Write-Host $_ }
            if ($result.Code -ne 0) { throw "compare-ledger failed (exit $($result.Code)): see the message above." }
            if ($private.Count -gt 0) {
                $folder = Join-Path (Join-Path (Join-Path $root 'reports') $Env) 'private'
                New-Item -ItemType Directory -Force -Path $folder | Out-Null
                $file = Join-Path $folder ('compare-ledger-{0}-{1:yyyy-MM-dd-HHmmss}.tsv' -f $Ledger, (Get-Date))
                Save-Utf8 $file $private
                Write-Host ''
                Write-Host "Details (dates, voucher numbers, amounts; local only, never share): $file"
            }
            return
        }
        if ($Service -eq 'analyse') {
            # `validate analyse`: tests explanations for every validation mismatch (counts,
            # patterns and Tally's standard names only). Reads Tally's own figures (read-only),
            # in the background like a sync, followed here.
            $job = [guid]::NewGuid().ToString()
            $analyseArgs = @('python', '-m', 'workers.cli', 'validate-analyse', '--connection', $connection, '--job', $job)
            foreach ($name in $Company) { $analyseArgs += @('--entity', $name) }
            Start-Followed 'analysis' $job $analyseArgs
            return
        }
        $validateArgs = @('python', '-m', 'workers.cli', 'validate', '--connection', $connection, '--source', 'tally')
        foreach ($name in $Company) { $validateArgs += @('--entity', $name) }
        if ($Quick) { $validateArgs += '--quick' }
        Invoke-Checked exec -T api @validateArgs
    }
    'transform' {
        # `transform retry`: transform the stored raw records again (those that failed, and
        # any left pending) with the current code, without contacting Tally, then validate
        # the companies it touched (validation reads Tally's own figures; -NoValidate skips
        # it). `transform rebuild`: the same for every stored object, processed ones too.
        # Runs in the background like a sync and is followed here (ADR-024).
        # `transform explain`: why references by name didn't resolve (counts and kinds only);
        # it reads only the database unless -CheckSource.
        if ($Service -notin @('retry', 'rebuild', 'explain')) { throw 'Usage: ./dev.ps1 transform retry|rebuild|explain [-Company "<name>"] [-NoValidate] [-CheckSource]' }
        Assert-EnvFile
        Assert-ApiRunning
        $job = [guid]::NewGuid().ToString()
        $retryArgs = @('python', '-m', 'workers.cli', "transform-$Service", '--connection', $connection, '--job', $job)
        foreach ($name in $Company) { $retryArgs += @('--entity', $name) }
        if ($NoValidate -and $Service -ne 'explain') { $retryArgs += '--no-validate' }
        if ($CheckSource -and $Service -eq 'explain') { $retryArgs += '--check-source' }
        Start-Followed 'transform' $job $retryArgs
    }
    'fields' {
        # The field catalogue: fields with no column (e.g. Tally UDFs), per entity. Field
        # names in the test environment only; elsewhere ids, kinds and counts.
        Assert-EnvFile
        Assert-ApiRunning
        Invoke-Checked exec -T api python -m workers.cli fields
    }
    'promote-field' {
        # Make a catalogued voucher field a reporting dimension, with backfill (ADR-025).
        if ($FieldId -le 0 -or -not $Code -or -not $Name) { throw 'Usage: ./dev.ps1 promote-field -FieldId <id from fields> -Code <CODE> -Name "<name>"' }
        Assert-EnvFile
        Assert-ApiRunning
        Invoke-Checked exec -T api python -m workers.cli promote-field --field-id $FieldId --code $Code --name $Name
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
        if ($Company.Count -ne 1) { throw 'extract needs -Company "<name>", e.g. ./dev.ps1 extract -Company "LedgerBridge Test Co"' }
        Assert-EnvFile
        Assert-ApiRunning
        Invoke-Stack exec -T api python -m workers.cli extract --connection $connection --source tally --entity $Company[0]
    }
    'diagrams' {
        # Regenerates the diagram sources that come from the code (ER and database diagrams,
        # from the SQLAlchemy models), then renders every docs/diagrams/*.mmd to SVG and PNG
        # with the official mermaid-cli image in a throwaway container. Needs no database,
        # no Tally and no running stack; starts and stops nothing else.
        $mermaidImage = 'ghcr.io/mermaid-js/mermaid-cli/mermaid-cli:11.4.2'
        $diagrams = Join-Path (Join-Path $root 'docs') 'diagrams'
        Push-Location (Join-Path $root 'data-plane')
        try {
            Invoke-Uv run python -m devtools.diagrams
            # The error catalogue is generated from the code too (core/problems.py).
            Invoke-Uv run python -m devtools.error_catalogue
            # So is the schema reference (every table and column, from the models).
            Invoke-Uv run python -m devtools.schema_reference
        }
        finally { Pop-Location }
        # Remove renders of sources that no longer exist (e.g. a diagram split in two).
        foreach ($render in Get-ChildItem -Path $diagrams -Include '*.svg', '*.png' -Recurse) {
            if (-not (Test-Path (Join-Path $diagrams "$($render.BaseName).mmd"))) { Remove-Item $render.FullName }
        }
        foreach ($source in Get-ChildItem -Path $diagrams -Filter '*.mmd') {
            $name = $source.BaseName
            foreach ($format in @('svg', 'png')) {
                $render = @('run', '--rm', '-v', "${diagrams}:/data", $mermaidImage,
                    '-i', "/data/$name.mmd", '-o', "/data/$name.$format", '-b', 'white',
                    '-c', '/data/mermaid-config.json')
                if ($format -eq 'png') { $render += @('-s', '2') }
                Invoke-ToolContainer $render "Rendering $name.$format"
            }
            Write-Host "Rendered $name (svg, png)"
        }
    }
    'docs-export' {
        # Word and PDF copies of the knowledge-base documents in docs/export/, with their
        # diagrams (PNG) embedded, made by the official pandoc Docker image in a throwaway
        # container. Run `./dev.ps1 diagrams` first so the diagrams are current. Needs no
        # database, no Tally and no running stack.
        $pandocImage = 'pandoc/latex:3.5'
        $docs = Join-Path $root 'docs'
        $export = Join-Path $docs 'export'
        New-Item -ItemType Directory -Force -Path $export | Out-Null
        $documents = @('rules/validation-and-conversion-rules.md', 'database/schema-reference.md', 'project-history.md')
        foreach ($document in $documents) {
            $folder = Split-Path -Parent $document
            $leaf = Split-Path -Leaf $document
            $name = [System.IO.Path]::GetFileNameWithoutExtension($leaf)
            # Documents sit at most one folder deep under docs/ (rules/, database/).
            $workdir = if ($folder) { "/data/$folder" } else { '/data' }
            foreach ($format in @('docx', 'pdf')) {
                $convert = @('run', '--rm', '-v', "${docs}:/data", '-w', $workdir, $pandocImage,
                    $leaf, '-o', "/data/export/$name.$format", '--toc', "--resource-path=.:$workdir")
                if ($format -eq 'pdf') {
                    $convert += @('--pdf-engine=xelatex', '-V', 'geometry:margin=1.6cm', '-V', 'fontsize=10pt')
                }
                Invoke-ToolContainer $convert "Exporting $name.$format"
            }
            Write-Host "Exported $name (docx, pdf)"
        }
        Write-Host "Saved in $export"
    }
    'seed-test-data' {
        # Writes into Tally (ADR-014): test environment and test company only. The tool itself
        # re-checks APP_ENV, that only one company is loaded and that its name matches exactly.
        if ($Env -ne 'test') { throw 'seed-test-data runs only against the test environment.' }
        Assert-Step 'seed-test-data' @('create-only', 'integrated-off', 'integrated-on')
        Assert-EnvFile
        if (-not $Company) { $Company = @('LedgerBridge Test Co') }
        Push-Location (Join-Path $root 'data-plane')
        # `seed-test-data create-only` creates missing items but skips alterations,
        # cancellations and deletions, so a sync can see vouchers before they change.
        $seedArgs = @('--company', $Company[0])
        if ($Service -eq 'create-only') { $seedArgs += '--create-only' }
        # `seed-test-data integrated-off` / `integrated-on` only switch the test company's
        # "Integrate Accounts with Inventory" (recordings with and without it).
        if ($Service -eq 'integrated-off') { $seedArgs += @('--integrated', 'no') }
        if ($Service -eq 'integrated-on') { $seedArgs += @('--integrated', 'yes') }
        try { Invoke-Uv run python -m devtools.tally_seed @seedArgs }
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
