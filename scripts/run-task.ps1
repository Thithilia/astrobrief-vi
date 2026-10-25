param([ValidateSet('collect','daily')][string]$Mode)
$ErrorActionPreference = 'Stop'
$taskProjectRoot = Split-Path -Parent $PSScriptRoot
$taskPython = Join-Path $taskProjectRoot '.venv\Scripts\python.exe'
$taskLogDirectory = Join-Path $taskProjectRoot '.local\logs'
New-Item -ItemType Directory -Path $taskLogDirectory -Force | Out-Null
Set-Location -LiteralPath $taskProjectRoot
$env:PYTHONIOENCODING = 'utf-8'
$taskLogPath = Join-Path $taskLogDirectory ((Get-Date -Format 'yyyy-MM-dd') + '-' + $Mode + '.log')
if ($Mode -eq 'daily') {
    & $taskPython -m pipeline daily --catch-up --refresh --publish *>> $taskLogPath
} else {
    & $taskPython -m pipeline collect --publish *>> $taskLogPath
}
exit $LASTEXITCODE
