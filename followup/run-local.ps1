param([string]$Python = "python", [switch]$OptionOrder, [switch]$BalancedKpi)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $repo 'runs/local-inference/runtime/ollama.exe'
if ($OptionOrder -and $BalancedKpi) {throw "Choose one study per run."}
$module = if ($BalancedKpi) {'followup.balanced-kpi.study'} elseif ($OptionOrder) {'followup.option-order.study'} else {'followup.study'}
$workPath = if ($BalancedKpi) {'runs/balanced-kpi'} elseif ($OptionOrder) {'runs/option-order'} else {'runs/followup'}
$work = (New-Item -Force -ItemType Directory (Join-Path $repo $workPath)).FullName
Set-Location $repo
& $Python -B -m $module freeze
if ($LASTEXITCODE) {exit $LASTEXITCODE}
$env:OLLAMA_HOST = '127.0.0.1:11707'
$env:OLLAMA_MODELS = 'D:\Models\E07'
$env:OLLAMA_NO_CLOUD = '1'
$env:OLLAMA_VULKAN = '1'
$env:OLLAMA_IGPU_ENABLE = '1'
$env:OLLAMA_CONTEXT_LENGTH = '2048'
$env:OLLAMA_MAX_LOADED_MODELS = '1'
$env:OLLAMA_NUM_PARALLEL = '1'
$env:TEMP = (New-Item -Force -ItemType Directory (Join-Path $work 'temp')).FullName
$env:TMP = $env:TEMP
if (Get-NetTCPConnection -LocalPort 11707 -State Listen -ErrorAction SilentlyContinue) {
    throw "Local experiment port is already in use."
}
$server = Start-Process $runtime -ArgumentList 'serve' -WindowStyle Hidden -PassThru -WorkingDirectory $work -RedirectStandardOutput (Join-Path $work 'ollama.out.log') -RedirectStandardError (Join-Path $work 'ollama.err.log')
try {
    $online = $false
    for ($i=0; $i -lt 30; $i++) {
        if ($server.HasExited) {throw "Server exited before collection."}
        try {
            $online = [bool](Invoke-RestMethod 'http://127.0.0.1:11707/api/version' -TimeoutSec 2).version
        } catch {Start-Sleep -Seconds 1}
        if ($online) {break}
    }
    if (!$online) {throw "Server startup timed out."}
    & $Python -B -u -m $module collect
    $status = $LASTEXITCODE
} finally {
    if (!$server.HasExited) {$server.Kill(); $server.WaitForExit()}
}
exit $status
