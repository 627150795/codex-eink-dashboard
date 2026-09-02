$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$launcher = Join-Path $projectRoot 'launch-hidden.vbs'
$taskName = 'Codex E-Ink Dashboard'
$wscript = Join-Path $env:WINDIR 'System32\wscript.exe'
$quotedLauncher = '"' + $launcher + '"'

$action = New-ScheduledTaskAction `
    -Execute $wscript `
    -Argument $quotedLauncher
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$watchdogTrigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 1) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $logonTrigger, $watchdogTrigger `
    -Principal $principal `
    -Settings $settings `
    -Description 'Shows local Codex tasks and quota on the paired SKD-CLOCK e-ink display.' `
    -Force | Out-Null

Start-ScheduledTask -TaskName $taskName
Write-Host "Installed and started: $taskName"
