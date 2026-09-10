$ErrorActionPreference = 'Stop'
$runtimeRoot = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies'
$pnpmCommand = Get-Command pnpm -ErrorAction SilentlyContinue
$pnpmExe = if ($pnpmCommand) { $pnpmCommand.Source } else { Join-Path $runtimeRoot 'bin/fallback/pnpm.cmd' }
$pythonExe = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (!(Test-Path -LiteralPath $pythonExe) -or !(Test-Path -LiteralPath (Join-Path $PSScriptRoot 'frontend/node_modules'))) { throw 'Run ./setup.ps1 first.' }
if (!(Test-Path -LiteralPath $pnpmExe)) { throw 'pnpm is required. See README.md.' }
foreach ($port in @(8000, 3000)) {
    $probe = [System.Net.Sockets.TcpClient]::new()
    try {
        $probe.Connect('127.0.0.1', $port)
        throw "Port $port is already in use. Stop the existing service or open http://127.0.0.1:3000 if V2 is running."
    } catch [System.Net.Sockets.SocketException] {
        # The port is available.
    } finally { $probe.Dispose() }
}
$dataDir = Join-Path $PSScriptRoot 'data'
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
$backend = Start-Process -FilePath $pythonExe -ArgumentList @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000') -WorkingDirectory (Join-Path $PSScriptRoot 'backend') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $dataDir 'backend.out.log') -RedirectStandardError (Join-Path $dataDir 'backend.err.log')
Push-Location (Join-Path $PSScriptRoot 'frontend')
try {
    Write-Host 'Idea Atelier: http://127.0.0.1:3000 — Ctrl+C stops the app.'
    & $pnpmExe dev
} finally {
    Pop-Location
    if (!$backend.HasExited) { Stop-Process -Id $backend.Id }
}
