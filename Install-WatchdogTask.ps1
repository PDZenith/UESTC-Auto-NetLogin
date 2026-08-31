[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$taskName = '\UESTC-NetLogin-Watchdog'
$baseDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$xmlPath = Join-Path $baseDir 'watchdog_task.xml'
$backupRoot = Join-Path $baseDir 'backups'

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    throw 'Administrator elevation is required. Open PowerShell as Administrator and run this script again.'
}

if (-not (Test-Path -LiteralPath $xmlPath -PathType Leaf)) {
    throw "Task XML not found: $xmlPath"
}

$savedErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
$existing = & "$env:SystemRoot\System32\schtasks.exe" /query /tn $taskName /xml 2>$null
$queryExitCode = $LASTEXITCODE
$ErrorActionPreference = $savedErrorActionPreference

if ($queryExitCode -eq 0 -and $existing) {
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $backupDir = Join-Path $backupRoot $stamp
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
    $backupPath = Join-Path $backupDir 'UESTC-NetLogin-Watchdog.previous.xml'
    Set-Content -LiteralPath $backupPath -Value $existing -Encoding Unicode
    Write-Host "Existing task exported to: $backupPath"
} elseif ($queryExitCode -ne 1) {
    throw "Unable to query the existing task; schtasks exited with code $queryExitCode"
}

& "$env:SystemRoot\System32\schtasks.exe" /create /tn $taskName /xml $xmlPath /f
if ($LASTEXITCODE -ne 0) {
    throw "Task registration failed with exit code $LASTEXITCODE"
}

& "$env:SystemRoot\System32\schtasks.exe" /query /tn $taskName /fo LIST /v
if ($LASTEXITCODE -ne 0) {
    throw "Task verification failed with exit code $LASTEXITCODE"
}

Write-Host 'Task registered successfully. It has not been started by this installer.'
