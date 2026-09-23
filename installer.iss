#ifndef AppName
  #error Build with build_installer.py
#endif

[Setup]
AppId=FanAssistants.{#AppName}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=lkghost327-afk
AppPublisherURL=https://github.com/lkghost327-afk/{#AppName}
DefaultDirName={localappdata}\Programs\FanAssistants\{#AppName}
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename={#AppName}-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
AppMutex=Local\FanAssistants.{#LowerCase(AppName)}
CloseApplications=no
RestartApplications=no
UninstallDisplayIcon={app}\{#AppName}.exe
SetupLogging=yes

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "docs\FIRST_RUN.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "docs\THIRD_PARTY.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "OWNERSHIP.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "PUBLISHER-KEY.xml"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppName}.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppName}.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppName}.exe"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  StartupCommand: String;
begin
  if CurUninstallStep = usUninstall then
    if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run',
      'FanAssistants.{#AppName}', StartupCommand) then
      if (CompareText(StartupCommand, '"' + ExpandConstant('{app}\{#AppName}.exe') + '" --background') = 0) or
         (CompareText(StartupCommand, ExpandConstant('{app}\{#AppName}.exe') + ' --background') = 0) then
        RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'FanAssistants.{#AppName}');
end;
