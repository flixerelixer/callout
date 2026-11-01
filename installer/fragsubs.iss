; FragSubs installer (Inno Setup 6).
; Built by CI:  iscc /DAppVersion=0.2.0 installer\fragsubs.iss
; Installs for the current user only (no admin prompt) into
; %LOCALAPPDATA%\Programs\FragSubs, which FragSubs can also update itself.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{07ED4603-2AF7-449D-B73B-D45FDB9C43B9}
AppName=FragSubs
AppVersion={#AppVersion}
AppVerName=FragSubs {#AppVersion}
AppPublisher=Handelsonderneming F.L. van Zanten
AppPublisherURL=https://fragsubs.com
AppSupportURL=https://fragsubs.com
AppUpdatesURL=https://fragsubs.com
DefaultDirName={localappdata}\Programs\FragSubs
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=FragSubs-Setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\FragSubs.exe
UninstallDisplayName=FragSubs
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
CloseApplications=force
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[InstallDelete]
; A clean program folder on every install, so no files from an older version linger.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\FragSubs\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\FragSubs"; Filename: "{app}\FragSubs.exe"
Name: "{autodesktop}\FragSubs"; Filename: "{app}\FragSubs.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\FragSubs.exe"; Description: "Start FragSubs"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Take the map detection file (Game State Integration) out of Counter-Strike 2's cfg folder.
Filename: "{app}\FragSubs.exe"; Parameters: "--remove-game-config"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveGameConfig"

[UninstallDelete]
; Files the self-updater may leave next to the program.
Type: filesandordirs; Name: "{app}\_internal.old"
Type: files; Name: "{app}\FragSubs.exe.old"

[Messages]
FinishedLabel=FragSubs is installed. Your settings and the downloaded speech model are kept in your user folder (AppData\Local\FragSubs), so reinstalling or updating never downloads them again.
