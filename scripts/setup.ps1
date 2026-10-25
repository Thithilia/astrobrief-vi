$ErrorActionPreference = 'Stop'
$taskProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskProjectRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) { python -m venv .venv }
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.lock.txt
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& npm.cmd ci
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& codex login status
Write-Output 'Setup complete. Read README.md before initializing collection and publication.'
