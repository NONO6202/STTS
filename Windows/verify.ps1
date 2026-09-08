param([string]$InstallDir = "", [switch]$InstallOnDisposableRunner)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$Validation = Join-Path $PSScriptRoot ('build\validation-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Force $Validation | Out-Null
$PreviousPath, $PreviousData, $PreviousPythonPath = $env:PATH, $env:STTS_DATA_DIR, $env:PYTHONPATH
try {
    if ($InstallOnDisposableRunner) {
        if ($env:GITHUB_ACTIONS -ne 'true') { throw 'Installer automation is limited to the disposable GitHub runner. Run Setup interactively on your PC.' }
        foreach ($Service in @('AudioEndpointBuilder', 'Audiosrv')) { Set-Service $Service -StartupType Manual; Start-Service $Service }
        $InstallDir = Join-Path $PSScriptRoot 'build\installed'
        $Installer = (Resolve-Path '..\dist\STTS-0.1.1-setup-x64.exe').Path
        $Process = Start-Process $Installer -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/DIR=`"$InstallDir`"", "/LOG=`"$Validation\installer.log`"") -WindowStyle Hidden -PassThru
        if (-not $Process.WaitForExit(600000)) { $Process.Kill(); throw 'Installer timed out' }
        if ($Process.ExitCode -notin @(0, 3010)) { throw "Installer failed: $($Process.ExitCode)" }
    }
    if (-not $InstallDir) { $InstallDir = Join-Path $PSScriptRoot 'build\bundle' }
    $Exe = Join-Path $InstallDir 'STTS.exe'
    if (-not (Test-Path $Exe)) { throw "Missing packaged app: $Exe" }
    $Marker = Join-Path $InstallDir 'build-complete.json'
    if (-not (Test-Path $Marker)) { throw 'The package build has not completed.' }
    $Built = Get-Content $Marker -Raw | ConvertFrom-Json
    if ((Get-FileHash $Exe).Hash -ne $Built.gui -or (Get-FileHash (Join-Path $InstallDir 'Engine\STTSWorker.exe')).Hash -ne $Built.worker) { throw 'Packaged executables do not match the completed build.' }
    if ((Get-FileHash (Join-Path $InstallDir 'STTSMicrophone.exe')).Hash -ne $Built.microphone) { throw 'Microphone helper does not match the completed build.' }
    $env:STTS_DATA_DIR = Join-Path $Validation 'data'
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot;$env:SystemRoot\System32\Wbem"
    $env:PYTHONPATH = $null
    foreach ($Check in @(@('--smoke-test', 'gui-smoke.json', 90), @('--diagnose-audio', 'audio-diagnostic.json', 30), @('--verify-install', 'flow.json', 2400))) {
        $Process = Start-Process $Exe -ArgumentList $Check[0] -WindowStyle Hidden -PassThru
        if (-not $Process.WaitForExit([int]$Check[2] * 1000)) { $Process.Kill(); throw "$($Check[0]) timed out" }
        $Result = Join-Path $env:STTS_DATA_DIR $Check[1]
        if ($Process.ExitCode -ne 0 -or -not (Test-Path $Result) -or -not (Get-Content $Result -Raw | ConvertFrom-Json).ok) { throw "Packaged verification failed: $Result" }
    }
    Write-Output "Packaged verification passed. Results: $Validation"
} finally {
    $env:PATH, $env:STTS_DATA_DIR, $env:PYTHONPATH = $PreviousPath, $PreviousData, $PreviousPythonPath
}
