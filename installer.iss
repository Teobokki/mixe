#define MyVer "1.0.0"
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
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\{#MyApp}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyApp}"; Filename: "{app}\{#MyApp}.exe"; IconFilename: "{app}\{#MyApp}.exe"
Name: "{group}\Uninstall {#MyApp}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyApp}"; Filename: "{app}\{#MyApp}.exe"; IconFilename: "{app}\{#MyApp}.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyApp}.exe"; Description: "Launch {#MyApp}"; Flags: nowait postinstall skipifsilent
