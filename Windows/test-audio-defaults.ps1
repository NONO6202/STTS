param([switch]$Integration)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$VSWhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$VSPath = & $VSWhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if ($LASTEXITCODE -ne 0 -or -not $VSPath) { throw 'Visual C++ build tools are required.' }
$DevCmd = Join-Path $VSPath 'Common7\Tools\VsDevCmd.bat'
New-Item -ItemType Directory -Force build\default-device-tests | Out-Null
$Test = if ($Integration) { 'default_devices_integration' } else { 'default_devices_test' }
$Script = @"
@echo off
call "$DevCmd" -arch=x64 -host_arch=x64
if errorlevel 1 exit /b 1
cl /nologo /std:c++17 /EHsc /W4 /O2 /MT /DUNICODE /D_UNICODE ..\Tests\$Test.cpp /Febuild\default-device-tests\$Test.exe /Fobuild\default-device-tests\$Test.obj /link Ole32.lib Advapi32.lib Propsys.lib
if errorlevel 1 exit /b 1
build\default-device-tests\$Test.exe
exit /b %errorlevel%
"@
Set-Content -LiteralPath build\default-device-tests\run.cmd -Value $Script -Encoding ascii
& cmd /d /c build\default-device-tests\run.cmd
if ($LASTEXITCODE -ne 0) { throw "Audio default tests failed: $LASTEXITCODE" }
