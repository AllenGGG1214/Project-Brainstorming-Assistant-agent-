$ErrorActionPreference = 'Stop'
$runtimeRoot = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies'
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
$pythonExe = if ($pythonCommand) { $pythonCommand.Source } else { Join-Path $runtimeRoot 'python/python.exe' }
$pnpmCommand = Get-Command pnpm -ErrorAction SilentlyContinue
$pnpmExe = if ($pnpmCommand) { $pnpmCommand.Source } else { Join-Path $runtimeRoot 'bin/fallback/pnpm.cmd' }
if (!(Test-Path -LiteralPath $pythonExe)) { throw 'Install Python 3.11+ and add python to PATH.' }
if (!(Test-Path -LiteralPath $pnpmExe)) { throw 'Install Node.js 20.9+ and pnpm, and add them to PATH.' }
Push-Location $PSScriptRoot
try {
    if (!(Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
        & $pythonExe -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Could not create Python virtual environment.' }
    }
    & './.venv/Scripts/python.exe' -m pip install -r backend/requirements.lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
    Push-Location frontend
    try {
        & $pnpmExe install --frozen-lockfile
        if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
    } finally { Pop-Location }
    Write-Host 'Ready. Run ./start.ps1; configure .env only when using live mode.'
} finally { Pop-Location }
