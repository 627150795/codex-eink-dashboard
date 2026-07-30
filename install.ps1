$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPath = Join-Path $projectRoot '.venv'

$launcher = Get-Command py -ErrorAction SilentlyContinue
if ($launcher) {
    & $launcher.Source -3 -m venv $venvPath
} else {
    $python = Get-Command python -ErrorAction Stop
    & $python.Source -m venv $venvPath
}

$venvPython = Join-Path $venvPath 'Scripts\python.exe'
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -e $projectRoot

Write-Host ''
Write-Host 'Installed. Next run:'
Write-Host "  .\start.ps1 preview --all --output previews"
Write-Host "  .\start.ps1 probe"
Write-Host "  .\start.ps1 once"
