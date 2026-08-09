param(
    [string]$PythonExe = "E:\ProgramData\anaconda3\envs\maixin\python.exe",
    [string]$EnvFile = ".env.local-ui.local"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$resolvedPython = (Resolve-Path -LiteralPath $PythonExe).Path
$resolvedEnv = (Resolve-Path -LiteralPath (Join-Path $projectRoot $EnvFile)).Path

Write-Host "MXZY-AI UI project: $projectRoot"
Write-Host "Configuration: $resolvedEnv"
Set-Location -LiteralPath $projectRoot
& $resolvedPython run_webviewer.py --env-file $resolvedEnv
exit $LASTEXITCODE
