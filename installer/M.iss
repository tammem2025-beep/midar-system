#define ProductName "M"
#define ProductVersion "0.25.1"
#define ProductPublisher "M Digital Business Management"

[Setup]
AppId={{9B603A66-E9BC-4E6F-A106-4A6F75430C9E}
AppName={#ProductName} — Digital Business Management
AppVersion={#ProductVersion}
AppPublisher={#ProductPublisher}
DefaultDirName={localappdata}\Programs\M
DefaultGroupName=M
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
OutputDir=output
OutputBaseFilename=M-Setup-{#ProductVersion}-Windows-x64
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName=M — Digital Business Management
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\M\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\frontend\*"; DestDir: "{app}\frontend"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\M"; Filename: "{app}\M.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\M"; Filename: "{app}\M.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\M.exe"; Description: "Launch M — Digital Business Management"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
; Intentionally do not remove %LOCALAPPDATA%\M: it contains the user's database, uploaded media, logs, and local settings.
