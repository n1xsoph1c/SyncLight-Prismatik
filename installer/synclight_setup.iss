#define MyAppName      "Synclight Bridge"
#define MyAppPublisher "n1xsoph1c"
#define MyAppURL       "https://github.com/n1xsoph1c/SyncLight-Prismatik"
#define MyAppExeName   "synclight.exe"
#define MyAppGUID      "{6A3C8F1D-2B4E-4F7A-9D0C-1E5A8B2F3C6D}"

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{#MyAppGUID}
AppName={#MyAppName}
AppVersion={#AppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=..\LICENSE
OutputDir=..\dist_installer
OutputBaseFilename=SynclightSetup
SetupIconFile=..\assets\icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon";   Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "runonstartup";  Description: "Start Synclight Bridge automatically at login"; GroupDescription: "Startup:"; Flags: unchecked
Name: "installprismatik"; Description: "Download and install Prismatik (Lightpack software)"; GroupDescription: "Optional components:"; Flags: unchecked

[Files]
Source: "..\dist\synclight\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}";          Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\{#MyAppName}";  Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "SynclightBridge"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue; Tasks: runonstartup

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "taskkill.exe"; Parameters: "/F /IM {#MyAppExeName}"; Flags: runhidden; RunOnceId: "KillApp"

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\SynclightBridge"

[Code]
var
  PrismatikPage: TWizardPage;

procedure DownloadAndInstallPrismatik();
var
  Http: Variant;
  Stream: Variant;
  JsonResp: string;
  UrlStart, UrlEnd: Integer;
  DownloadUrl, TmpFile: string;
  ResultCode: Integer;
begin
  try
    Http := CreateOleObject('WinHttp.WinHttpRequest.5.1');
    Http.Open('GET', 'https://api.github.com/repos/psieg/Lightpack/releases/latest', False);
    Http.SetRequestHeader('User-Agent', 'SynclightInstaller');
    Http.Send();
    JsonResp := Http.ResponseText;

    // Find the 64-bit Windows setup URL: "Prismatik.unofficial.64bit.Setup.*.exe"
    // Anchor on the stable part of the filename, then find the enclosing URL
    UrlStart := Pos('64bit.Setup.', JsonResp);
    if UrlStart = 0 then
    begin
      MsgBox('Could not find Prismatik x64 installer URL. Please install manually from https://github.com/psieg/Lightpack/releases', mbError, MB_OK);
      Exit;
    end;

    // Walk forward to the closing .exe"
    UrlEnd := UrlStart;
    while (UrlEnd < Length(JsonResp) - 4) and
          not ((JsonResp[UrlEnd]   = '.') and
               (JsonResp[UrlEnd+1] = 'e') and
               (JsonResp[UrlEnd+2] = 'x') and
               (JsonResp[UrlEnd+3] = 'e') and
               (JsonResp[UrlEnd+4] = '"')) do
      UrlEnd := UrlEnd + 1;
    UrlEnd := UrlEnd + 3; // point at last 'e' of .exe

    // Walk back to the opening quote of https://
    while (UrlStart > 1) and (JsonResp[UrlStart] <> '"') do
      UrlStart := UrlStart - 1;
    UrlStart := UrlStart + 1;

    DownloadUrl := Copy(JsonResp, UrlStart, UrlEnd - UrlStart + 1);

    TmpFile := ExpandConstant('{tmp}\PrismatikSetup_x64.exe');

    // Download the installer
    Http.Open('GET', DownloadUrl, False);
    Http.SetRequestHeader('User-Agent', 'SynclightInstaller');
    Http.Send();

    // Write binary response to file using ADODB.Stream
    Stream := CreateOleObject('ADODB.Stream');
    Stream.Type_ := 1; // binary
    Stream.Open();
    Stream.Write(Http.ResponseBody);
    Stream.SaveToFile(TmpFile, 2);
    Stream.Close();

    // Run installer silently
    if not Exec(TmpFile, '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART', '', SW_SHOW, ewWaitUntilTerminated, ResultCode) then
      MsgBox('Prismatik installer failed to launch. You can install it manually from https://github.com/psieg/Lightpack/releases', mbError, MB_OK);

  except
    MsgBox('Failed to download Prismatik: ' + GetExceptionMessage() + #13#10 + 'Please install manually from https://github.com/psieg/Lightpack/releases', mbError, MB_OK);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    if IsTaskSelected('installprismatik') then
      DownloadAndInstallPrismatik();
  end;
end;
