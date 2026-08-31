[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$mainTaskName = 'UESTC-NetLogin-Watchdog'
$probeTaskName = 'UESTC-NetLogin-SystemProbe'
$baseDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$probeBatch = Join-Path $baseDir 'run_system_probe.bat'
$probeLog = Join-Path $baseDir 'system_probe_log.txt'
$backupRoot = Join-Path $baseDir 'backups'
$runId = Get-Date -Format 'yyyyMMdd_HHmmss'

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Administrator elevation is required. Open PowerShell as Administrator and run this script again.'
}

if (-not (Test-Path -LiteralPath $probeBatch -PathType Leaf)) {
    throw "System probe batch file not found: $probeBatch"
}

$mainTask = Get-ScheduledTask -TaskName $mainTaskName
if (-not $mainTask.Settings.Enabled) {
    throw "Main watchdog task is not enabled: $mainTaskName"
}
if ($mainTask.Principal.UserId -notin @('SYSTEM', 'S-1-5-18')) {
    throw "Main watchdog is not running as SYSTEM: $($mainTask.Principal.UserId)"
}

$existingProbe = Get-ScheduledTask -TaskName $probeTaskName -ErrorAction SilentlyContinue
if ($existingProbe) {
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $backupDir = Join-Path $backupRoot $stamp
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
    $backupPath = Join-Path $backupDir 'UESTC-NetLogin-SystemProbe.previous.xml'
    Export-ScheduledTask -TaskName $probeTaskName | Set-Content -LiteralPath $backupPath -Encoding Unicode
    Write-Host "Previous probe task exported to: $backupPath"
}

$cmdPath = Join-Path $env:SystemRoot 'System32\cmd.exe'
$arguments = "/d /c `"`"$probeBatch`" $runId`""
$action = New-ScheduledTaskAction -Execute $cmdPath -Argument $arguments -WorkingDirectory $baseDir
$systemPrincipal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 4) `
    -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName $probeTaskName `
    -Action $action `
    -Principal $systemPrincipal `
    -Settings $settings `
    -Description 'One-shot SYSTEM account browser probe for NetLogin pre-reboot validation.' `
    -Force | Out-Null

$startedAt = Get-Date
Start-ScheduledTask -TaskName $probeTaskName
Write-Host "SYSTEM browser probe started. run_id=$runId"

$completed = $false
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    Start-Sleep -Seconds 2
    $task = Get-ScheduledTask -TaskName $probeTaskName
    $info = Get-ScheduledTaskInfo -TaskName $probeTaskName
    if ($info.LastRunTime -ge $startedAt.AddSeconds(-2) -and $task.State -ne 'Running') {
        $completed = $true
        break
    }
}

Disable-ScheduledTask -TaskName $probeTaskName | Out-Null
if (-not $completed) {
    throw 'SYSTEM browser probe did not finish within 120 seconds. The probe task has been disabled.'
}
if ($info.LastTaskResult -ne 0) {
    throw "SYSTEM browser probe failed with task result $($info.LastTaskResult). The probe task has been disabled."
}

$logText = Get-Content -Raw -Encoding UTF8 -LiteralPath $probeLog
$startMarker = "[SystemProbeStart] run_id=$runId"
$endMarker = "[SystemProbeEnd] run_id=$runId exit_code=0"
$runStart = $logText.LastIndexOf($startMarker, [StringComparison]::Ordinal)
if ($runStart -lt 0) {
    throw "Probe log is missing the start marker for run_id=$runId"
}
$runLog = $logText.Substring($runStart)
if (-not $runLog.Contains($endMarker)) {
    throw "Probe log is missing a successful end marker for run_id=$runId"
}
if (-not $runLog.Contains('probe_succeeded')) {
    throw 'Probe did not reach the compatible portal success state.'
}
if ($runLog.Contains('login_submitted')) {
    throw 'Safety violation: the SYSTEM probe submitted a real login.'
}

$mainTaskAfter = Get-ScheduledTask -TaskName $mainTaskName
if (-not $mainTaskAfter.Settings.Enabled) {
    throw 'Main watchdog became disabled during the probe.'
}

Write-Host 'PASS: SYSTEM launched the project Python, ChromeDriver, and Headless Chrome.'
Write-Host 'PASS: Portal probe succeeded without reading or submitting credentials.'
Write-Host 'PASS: Probe task is disabled and the main watchdog remains enabled.'
Write-Host "Probe log: $probeLog"
