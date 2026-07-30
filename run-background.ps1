$ErrorActionPreference = 'Continue'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$logFolder = Join-Path $projectRoot 'logs'
$logPath = Join-Path $logFolder 'dashboard.log'
$previewPath = Join-Path $projectRoot 'previews\live.png'
$configPath = Join-Path $projectRoot 'config.json'
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
New-Item -ItemType Directory -Path $logFolder -Force | Out-Null

function Write-DashboardLog {
    param([AllowEmptyString()][string]$Message)
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message"
    $line | Out-File -LiteralPath $logPath -Encoding utf8 -Append
}

Write-DashboardLog "service-start wrapper-pid=$PID"
$exitCode = 1

if (-not (Test-Path -LiteralPath $python)) {
    Write-DashboardLog 'service-error Python environment is not installed'
} else {
    Push-Location $projectRoot
    try {
        & $python -m codex_eink --config $configPath run --preview $previewPath 2>&1 |
            ForEach-Object { Write-DashboardLog "$_" }
        $exitCode = $LASTEXITCODE
    } catch {
        Write-DashboardLog "service-error $($_.Exception.Message)"
        $exitCode = 1
    } finally {
        Pop-Location
    }
}

Write-DashboardLog "service-exit code=$exitCode"
exit $exitCode
