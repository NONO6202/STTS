#if !FileExists("build\bundle\build-complete.json")
  #error Build the complete app bundle before compiling Setup.
#endif
#define AppVersion "0.1.0"
[Setup]
AppId={{7B7D5075-8B32-4F58-B765-9C15BA062001}
AppName=STTS
AppVersion={#AppVersion}
AppPublisher=NONO6202
AppPublisherURL=https://github.com/NONO6202/STTS
DefaultDirName={autopf}\STTS
DefaultGroupName=STTS
UninstallDisplayIcon={app}\STTS.exe
OutputDir=..\dist
OutputBaseFilename=STTS-{#AppVersion}-setup-x64
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.22000
PrivilegesRequired=admin
Compression=lzma2/ultra64
LZMAUseSeparateProcess=yes
SolidCompression=yes
CompressionThreads=4
WizardStyle=modern
InfoBeforeFile=VB-CABLE-NOTICE.txt
SetupLogging=yes
CloseApplications=yes
RestartApplications=no
ChangesAssociations=no

[Files]
Source: "build\bundle\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "build\VB-CABLE\*"; DestDir: "{app}\VB-CABLE"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "VB-CABLE-NOTICE.txt"; DestDir: "{app}"
Source: "README.md"; DestDir: "{app}"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "STTS"; Flags: uninsdeletevalue

[Icons]
Name: "{group}\STTS"; Filename: "{app}\STTS.exe"
Name: "{group}\VB-CABLE (VB-Audio)"; Filename: "{app}\VB-CABLE\VBCABLE_ControlPanel.exe"
Name: "{group}\VB-CABLE information and donation"; Filename: "https://www.vb-cable.com/"
Name: "{group}\Uninstall STTS"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\STTS.exe"; Description: "Launch STTS"; Flags: nowait postinstall skipifsilent runasoriginaluser; Check: Not DriverInstalledNow

[Code]
var
  InstalledDriver: Boolean;

function DriverExists: Boolean;
var
  Service, Devices: Variant;
begin
  Result := False;
  try
    Service := GetActiveOleObject('WbemScripting.SWbemLocator');
  except
    Service := CreateOleObject('WbemScripting.SWbemLocator');
  end;
  try
    Service := Service.ConnectServer('', 'root\CIMV2');
    Devices := Service.ExecQuery('SELECT Name FROM Win32_PnPEntity WHERE Name LIKE ''%VB-Audio Virtual Cable%''');
    Result := Devices.Count > 0;
  except
    Log('Could not enumerate audio devices.');
  end;
end;

function DriverInstalledNow: Boolean;
begin
  Result := InstalledDriver;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode, Attempt: Integer;
begin
  if (CurStep = ssPostInstall) and not DriverExists then
  begin
    WizardForm.StatusLabel.Caption := 'Installing VB-CABLE virtual microphone by VB-Audio...';
    if not Exec(ExpandConstant('{app}\VB-CABLE\VBCABLE_Setup_x64.exe'), '-i -h',
      ExpandConstant('{app}\VB-CABLE'), SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      RaiseException('VB-CABLE installer could not start. Please run STTS Setup again.');
    Log(Format('VB-CABLE setup exit code: %d', [ResultCode]));
    for Attempt := 1 to 30 do
    begin
      if DriverExists then Break;
      Sleep(1000);
    end;
    if not DriverExists then
      RaiseException('VB-CABLE installation could not be confirmed. Restart the PC and run STTS Setup again.');
    InstalledDriver := True;
  end;
end;

function NeedRestart: Boolean;
begin
  Result := InstalledDriver;
end;
