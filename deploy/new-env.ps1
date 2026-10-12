<#
.SYNOPSIS
    Creates .env.<Env> from .env.<Env>.example with strong random passwords.

.DESCRIPTION
    Every MySQL password (root, app_rw, migrator, report_ro, ai_ro) gets 32 random letters and
    digits from the operating system's cryptographic generator. Everything else is copied
    from the example unchanged. The passwords are never printed.

    Refuses if the target file already exists: the MySQL volume was initialised with the
    passwords in it, and replacing them would lock the services out of their own database.

    Called by `./dev.ps1 init-env -Env <env>`. -OutFile writes elsewhere (used to try the
    script without touching a real env file).

.EXAMPLE
    ./deploy/new-env.ps1 -Env pilot
#>
param(
    [ValidateSet('test', 'pilot')]
    [string]$Env = 'pilot',

    [string]$OutFile = ''
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$example = Join-Path $repoRoot ".env.$Env.example"
$target = if ($OutFile) { $OutFile } else { Join-Path $repoRoot ".env.$Env" }

$secretKeys = @(
    'MYSQL_ROOT_PASSWORD',
    'MYSQL_APP_PASSWORD',
    'MYSQL_MIGRATOR_PASSWORD',
    'MYSQL_REPORT_PASSWORD',
    'MYSQL_AI_PASSWORD'
)

function New-Secret([int]$Length = 32) {
    # Letters and digits only, so the value needs no quoting in env files or shells.
    # Rejection sampling keeps every character equally likely.
    $alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $chars = New-Object System.Collections.Generic.List[char]
    $buffer = New-Object byte[] 64
    try {
        while ($chars.Count -lt $Length) {
            $rng.GetBytes($buffer)
            foreach ($b in $buffer) {
                if ($b -lt 248 -and $chars.Count -lt $Length) { $chars.Add($alphabet[$b % 62]) }
            }
        }
    }
    finally { $rng.Dispose() }
    return -join $chars
}

if (-not (Test-Path $example)) { throw "Missing $example." }
if (Test-Path $target) {
    throw "$target already exists; not replacing it. Its passwords are the ones the MySQL " +
        "volume was created with. To start over, back it up, remove the stack with " +
        "'./deploy/stack.ps1 -Env $Env down -v' (deletes that environment's data), then delete the file."
}

$generated = @()
$lines = foreach ($line in Get-Content $example) {
    $key = ($line -split '=', 2)[0]
    if ($secretKeys -contains $key) {
        $generated += $key
        "$key=$(New-Secret)"
    }
    else { $line }
}
$missing = $secretKeys | Where-Object { $generated -notcontains $_ }
if ($missing) { throw "The example has no line for: $($missing -join ', '). Nothing written." }

# UTF-8 without a byte-order mark, which Docker Compose and pydantic read cleanly.
[System.IO.File]::WriteAllLines($target, [string[]]$lines, (New-Object System.Text.UTF8Encoding $false))
Write-Host "Created $target with new random values for: $($generated -join ', ')."
Write-Host 'The values are not shown. Keep a backup of this file somewhere safe (e.g. a password manager); never commit it.'
