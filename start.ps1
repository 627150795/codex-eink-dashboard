$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Not installed yet. Run .\install.ps1 first.'
}

Push-Location $projectRoot
try {
    & $python -m codex_eink @args
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
