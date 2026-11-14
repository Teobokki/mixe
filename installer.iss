#define MyVer "2.0.1"
#define MyApp "MIXE"
[Setup]
AppId={{A1D8E4C2-9F70-4B3E-8C15-6D2A9E7B4F01}
AppName={#MyApp}
AppVersion={#MyVer}
AppVerName={#MyApp} {#MyVer}
AppPublisher=EX Inc./HYPERION DIGITAL
AppPublisherURL=https://github.com/Teobokki/mixe
AppCopyright=©2026 EX Inc./HYPERION DIGITAL ©2026
VersionInfoVersion={#MyVer}.0
VersionInfoCompany=EX Inc.
VersionInfoCopyright=©2026 EX Inc./HYPERION DIGITAL ©2026
VersionInfoProductName={#MyApp}
VersionInfoDescription={#MyApp} Setup
DefaultDirName={localappdata}\Programs\{#MyApp}
DefaultGroupName={#MyApp}
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
UsePreviousPrivileges=no
UsePreviousAppDir=yes
OutputDir=dist
OutputBaseFilename=MIXE-Setup-{#MyVer}
SetupIconFile=assets\logo.ico
WizardImageFile=assets\wizard_large.bmp,assets\wizard_large2x.bmp
WizardSmallImageFile=assets\wizard_small.bmp,assets\wizard_small2x.bmp
UninstallDisplayIcon={app}\{#MyApp}.exe
UninstallDisplayName={#MyApp}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force
RestartApplications=no
SetupLogging=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\{#MyApp}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs uninsrestartdelete

[Icons]
Name: "{group}\{#MyApp}"; Filename: "{app}\{#MyApp}.exe"; IconFilename: "{app}\{#MyApp}.exe"
Name: "{group}\Uninstall {#MyApp}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyApp}"; Filename: "{app}\{#MyApp}.exe"; IconFilename: "{app}\{#MyApp}.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyApp}.exe"; Description: "Launch {#MyApp}"; Flags: nowait postinstall skipifsilent

[Code]
procedure QuietExec(const Cmd, Params: String);
var
  RC: Integer;
begin
  Exec(Cmd, Params, '', SW_HIDE, ewWaitUntilTerminated, RC);
end;

procedure KillOldMixe;
begin
  { 1.0.0 launched QEMU in a new process group, so closing MIXE.exe alone can leave qemu-system-x86_64w.exe locking _internal\engine. }
  QuietExec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM MIXE.exe /T');
  QuietExec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM qemu-system-x86_64w.exe /T');
  QuietExec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM qemu-system-x86_64.exe /T');
  QuietExec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM qemu-img.exe /T');
end;

procedure StripReadOnly(const Dir: String);
begin
  if DirExists(Dir) then
    QuietExec(ExpandConstant('{cmd}'), '/C attrib -R "' + Dir + '\*.*" /S /D');
end;

procedure TryRemoveDir(const Dir: String);
var
  I: Integer;
begin
  if not DirExists(Dir) then
    Exit;
  StripReadOnly(Dir);
  I := 0;
  while (I < 5) and DirExists(Dir) do
  begin
    DelTree(Dir, True, True, True);
    if not DirExists(Dir) then
      Exit;
    Sleep(400);
    I := I + 1;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  AppDir: String;
begin
  NeedsRestart := False;
  KillOldMixe;
  Sleep(500);
  AppDir := ExpandConstant('{app}');
  if AppDir <> '' then
  begin
    StripReadOnly(AppDir);
    { Drop the 1.0.0 engine and the whole previous _internal tree so a locked leftover cannot abort a silent upgrade. Failures are ignored; new files still copy. }
    TryRemoveDir(AppDir + '\_internal\engine');
    TryRemoveDir(AppDir + '\engine');
    TryRemoveDir(AppDir + '\_internal');
  end;
  Result := '';
end;
