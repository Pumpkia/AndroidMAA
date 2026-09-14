#ifndef AppVersion
  #define AppVersion "2.1.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\.packaging-build\dist\NnMaa"
#endif
#ifndef OutputDir
  #define OutputDir "..\release"
#endif
#ifndef OutputBaseFilename
  #define OutputBaseFilename "NnMaa-v2.1.0-setup"
#endif
#ifndef IconPath
  #define IconPath "..\assets\icons\nnmaa.ico"
#endif

[Setup]
AppId={{D2B72385-6B43-4F52-A908-8E381C39141F}
AppName=NnMaa
AppVersion={#AppVersion}
AppVerName=NnMaa {#AppVersion}
AppPublisher=Pumpkia
AppPublisherURL=https://github.com/Pumpkia/NnMaa
AppSupportURL=https://github.com/Pumpkia/NnMaa/issues
DefaultDirName={autopf}\NnMaa
DefaultGroupName=NnMaa
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBaseFilename}
SetupIconFile={#IconPath}
UninstallDisplayIcon={app}\NnMaa.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#AppVersion}.0
VersionInfoCompany=Pumpkia
VersionInfoDescription=NnMaa Android Automation Workbench
VersionInfoProductName=NnMaa
VersionInfoProductVersion={#AppVersion}

[Languages]
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Excludes: "portable.flag"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "ChineseSimplified.LICENSE"; DestDir: "{app}\licenses"; DestName: "Inno-Setup-ChineseSimplified.LICENSE.txt"; Flags: ignoreversion

[InstallDelete]
Type: files; Name: "{app}\portable.flag"

[Icons]
Name: "{group}\NnMaa"; Filename: "{app}\NnMaa.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\NnMaa"; Filename: "{app}\NnMaa.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\NnMaa.exe"; Description: "{cm:LaunchProgram,NnMaa}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: dirifempty; Name: "{app}\platform-tools"
Type: dirifempty; Name: "{app}"

[Code]
procedure StopBundledAdbProcess();
var
  PowerShellPath: String;
  AdbPath: String;
  Parameters: String;
  ResultCode: Integer;
begin
  PowerShellPath := ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe');
  AdbPath := ExpandConstant('{app}\platform-tools\adb.exe');
  if not FileExists(PowerShellPath) then
    Exit;

  StringChangeEx(AdbPath, '''', '''''', True);
  Parameters := '-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$target = ''' + AdbPath + '''; Get-CimInstance Win32_Process | Where-Object { $_.Name -eq ''adb.exe'' -and $_.ExecutablePath -and [String]::Equals($_.ExecutablePath, $target, [StringComparison]::OrdinalIgnoreCase) } | ForEach-Object { Invoke-CimMethod -InputObject $_ -MethodName Terminate | Out-Null }"';
  Exec(PowerShellPath, Parameters, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopBundledAdbProcess();
  Result := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    StopBundledAdbProcess();
end;
