; Reusable installer. Override AppVersion, SourceDir and OutputDir with ISCC /D.
#ifndef AppVersion
  #define AppVersion "1.6.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\BounceMusic"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif
#ifndef ProductId
  #define ProductId "A58D6CD5-11F8-476E-8D46-7E0D0361CB17"
#endif
#ifndef AppMutexName
  #define AppMutexName "Local\BounceMusic-Desktop-SingleInstance"
#endif

[Setup]
AppId={{{#ProductId}}
AppName=Q弹音乐
AppVersion={#AppVersion}
AppPublisher=葵猫猫
AppPublisherURL=https://github.com/Aoineko-UwU/BounceMusic
AppSupportURL=https://github.com/Aoineko-UwU/BounceMusic/issues
AppUpdatesURL=https://github.com/Aoineko-UwU/BounceMusic/releases
DefaultDirName={localappdata}\Programs\BounceMusic
DefaultGroupName=Q弹音乐
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=BounceMusic-v{#AppVersion}-Setup-win64
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\BounceMusic.exe
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
AppMutex={#AppMutexName}
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "chinese"; MessagesFile: "compiler:Default.isl,ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式："

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "install.marker"; DestDir: "{app}"; DestName: ".bounce-installed"; Flags: ignoreversion

[Icons]
Name: "{group}\Q弹音乐"; Filename: "{app}\BounceMusic.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Q弹音乐"; Filename: "{app}\BounceMusic.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\BounceMusic.exe"; Description: "启动 Q弹音乐"; Flags: nowait postinstall skipifsilent
