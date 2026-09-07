param([switch]$SkipDependencies, [switch]$SkipInstaller, [string]$Compiler = "")
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$BundlePath = Join-Path $PSScriptRoot 'build\bundle'
$Running = Get-Process STTS, STTSWorker, STTSCapture -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith($BundlePath + '\', [StringComparison]::OrdinalIgnoreCase) }
if ($Running) { throw 'Close the packaged verification processes before rebuilding.' }
$BuildMarker = Join-Path $BundlePath 'build-complete.json'
if (Test-Path $BuildMarker) { Remove-Item -LiteralPath $BuildMarker }

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed with exit code $LASTEXITCODE" }
}
if (-not (Test-Path 'build-env\Scripts\python.exe')) { Invoke-Checked python @('-m', 'venv', 'build-env') }
$Python = Join-Path $PSScriptRoot 'build-env\Scripts\python.exe'
function Invoke-Freeze {
    param([string[]]$Arguments)
    $PreviousPath, $PreviousPythonPath = $env:PATH, $env:PYTHONPATH
    try {
        # Unrelated tools can provide identically named but incompatible DLLs
        # (for example Poppler's icuuc.dll instead of Windows' ICU API).
        $env:PATH = "$(Split-Path $Python);$env:SystemRoot\System32;$env:SystemRoot;$env:SystemRoot\System32\Wbem"
        $env:PYTHONPATH = $null
        Invoke-Checked $Python $Arguments
    } finally {
        $env:PATH, $env:PYTHONPATH = $PreviousPath, $PreviousPythonPath
    }
}
if (-not $SkipDependencies) {
Invoke-Checked $Python @('-m', 'pip', 'install', '--upgrade', 'pip')
Invoke-Checked $Python @('-m', 'pip', 'install', '--no-cache-dir', 'torch==2.10.0', 'torchaudio==2.10.0', '--index-url', 'https://download.pytorch.org/whl/cu128')
Invoke-Checked $Python @('-m', 'pip', 'install', '-r', 'requirements.txt')
Invoke-Checked $Python @('-m', 'pip', 'install', '--no-deps', 'qwen-tts==0.1.1')
# These distributions share a Python namespace. Keep only the DirectML build, which also includes CPU.
Invoke-Checked $Python @('-m', 'pip', 'uninstall', '-y', 'onnxruntime')
Invoke-Checked $Python @('-m', 'pip', 'install', '--no-deps', '--force-reinstall', 'onnxruntime-directml==1.24.3')
}
New-Item -ItemType Directory -Force build, build\bundle, build\VB-CABLE | Out-Null
$Zip = 'vendor\VBCABLE_Driver_Pack45.zip'
if (-not (Test-Path $Zip)) {
    New-Item -ItemType Directory -Force vendor | Out-Null
    Invoke-WebRequest 'https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack45.zip' -OutFile $Zip
}
if ((Get-FileHash $Zip -Algorithm SHA256).Hash.ToLower() -ne 'b950e39f01af1d04ea623c8f6d8eb9b6ea5c477c637295fabf20631c85116bfb') { throw 'VB-CABLE archive hash mismatch' }
Expand-Archive $Zip 'build\VB-CABLE' -Force
$Signature = Get-AuthenticodeSignature 'build\VB-CABLE\vbaudio_cable64_win10.cat'
$Signature | Select-Object Status, StatusMessage, SignerCertificate | Format-List
if ($Signature.Status -ne 'Valid') { throw 'VB-CABLE catalog signature is not valid' }
$VSWhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$VSPath = & $VSWhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
$DevCmd = Join-Path $VSPath 'Common7\Tools\VsDevCmd.bat'
$NativeScript = "@echo off`r`ncall `"$DevCmd`" -arch=x64 -host_arch=x64`r`nif errorlevel 1 exit /b 1`r`ncl /nologo /std:c++17 /EHsc /W4 /O2 /MT /DUNICODE /D_UNICODE native\capture.cpp /Febuild\bundle\STTSCapture.exe /Fobuild\capture.obj /link Ole32.lib Mmdevapi.lib RuntimeObject.lib`r`nif errorlevel 1 exit /b 1`r`ncl /nologo /std:c++17 /EHsc /W4 /O2 /MT native\gpu.cpp /Febuild\bundle\STTSGPU.exe /Fobuild\gpu.obj /link Dxgi.lib D3d12.lib`r`nexit /b %errorlevel%`r`n"
Set-Content 'build\native-build.cmd' $NativeScript -Encoding ascii
Invoke-Checked cmd @('/d', '/c', 'build\native-build.cmd')
Invoke-Freeze -Arguments @('-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--console', '--name', 'STTSWorker',
    '--distpath', 'build\frozen', '--workpath', 'build\pyinstaller-worker', '--specpath', 'build',
    '--add-data', "$PSScriptRoot\models.json;.", '--collect-all', 'qwen_tts', '--collect-all', 'faster_whisper',
    '--collect-all', 'sounddevice', '--collect-all', 'supertonic', '--collect-all', 'transformers', '--collect-all', 'torchaudio',
    '--collect-all', 'onnxruntime', '--collect-all', 'librosa', '--copy-metadata', 'qwen-tts', '--copy-metadata', 'torch',
    '--copy-metadata', 'accelerate', '--copy-metadata', 'safetensors', '--exclude-module', 'bitsandbytes', '--exclude-module', 'onnx', '--hidden-import', 'scipy.special._cdflib', '--exclude-module', 'PySide6', 'worker.py')
Invoke-Freeze -Arguments @('-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--windowed', '--name', 'STTS',
    '--distpath', 'build\frozen', '--workpath', 'build\pyinstaller-gui', '--specpath', 'build',
    '--add-data', "$PSScriptRoot\..\Support\speech_languages.json;.", '--add-data', "$PSScriptRoot\models.json;.", '--collect-all', 'sounddevice',
    '--collect-submodules', 'pycaw', '--exclude-module', 'torch', '--exclude-module', 'transformers', '--exclude-module', 'qwen_tts', 'app.py')
# Keep each frozen Python runtime separate; merging _internal can overwrite DLLs
# used by the worker when only the GUI is rebuilt with a different Python version.
New-Item -ItemType Directory -Force 'build\bundle\Engine' | Out-Null
Copy-Item 'build\frozen\STTSWorker\*' 'build\bundle\Engine' -Recurse -Force
Copy-Item 'build\bundle\STTSGPU.exe' 'build\bundle\Engine\STTSGPU.exe' -Force
Copy-Item 'build\frozen\STTS\*' 'build\bundle' -Recurse -Force
Invoke-Checked $Python @('collect_licenses.py', 'build\bundle\Licenses')
@{
    version = '0.1.0'
    gui = (Get-FileHash 'build\bundle\STTS.exe' -Algorithm SHA256).Hash
    worker = (Get-FileHash 'build\bundle\Engine\STTSWorker.exe' -Algorithm SHA256).Hash
} | ConvertTo-Json | Set-Content -LiteralPath $BuildMarker -Encoding utf8
if ($SkipInstaller) { return }
$ISCC = if ($Compiler) { $Compiler } else { "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
if (-not (Test-Path $ISCC)) { throw 'Install Inno Setup 6 before building.' }
Invoke-Checked $ISCC @('installer.iss')
Get-FileHash '..\dist\STTS-0.1.0-setup-x64.exe' -Algorithm SHA256
