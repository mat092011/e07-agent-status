param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$rootDir = Split-Path -Parent $PSScriptRoot
$runDir = Join-Path $rootDir 'runs/local-inference'
$modelDir = (New-Item -Force -ItemType Directory -Path 'D:\Models\E07').FullName
$scratchDir = (New-Item -Force -ItemType Directory -Path (Join-Path $runDir 'temp')).FullName
$env:OLLAMA_MODELS = $modelDir
$env:OLLAMA_HOST = '127.0.0.1:11707'
$env:OLLAMA_CONTEXT_LENGTH = '2048'
$env:OLLAMA_MAX_LOADED_MODELS = '1'
$env:OLLAMA_NUM_PARALLEL = '1'
$env:OLLAMA_NO_CLOUD = '1'
$env:OLLAMA_VULKAN = '1'
$env:OLLAMA_IGPU_ENABLE = '1'
$env:TEMP = $scratchDir
$env:TMP = $scratchDir
$ollama = Join-Path $runDir 'runtime\ollama.exe'
if (Get-NetTCPConnection -LocalPort 11707 -State Listen -ErrorAction SilentlyContinue) {
    throw 'The experiment port is already occupied.'
}
$server = Start-Process -FilePath $ollama -ArgumentList 'serve' -WindowStyle Hidden -PassThru -WorkingDirectory $runDir -RedirectStandardOutput (Join-Path $runDir 'server.stdout.log') -RedirectStandardError (Join-Path $runDir 'server.stderr.log')
try {
    $online = $false
    for ($i=0; $i -lt 60; $i++) {
        if ($server.HasExited) { throw 'Local server exited during startup.' }
        try {
            $version = Invoke-RestMethod 'http://127.0.0.1:11707/api/version' -TimeoutSec 2
            if ($version.version) { $online = $true; break }
        } catch { Start-Sleep -Seconds 1 }
    }
    if (-not $online) {throw 'Server startup timed out.'}
    Set-Location $rootDir
    & $Python -B -u (Join-Path $PSScriptRoot 'collect.py')
    $queueExit = $LASTEXITCODE
} finally {
    if (-not $server.HasExited) { $server.Kill(); $server.WaitForExit() }
}
exit $queueExit
