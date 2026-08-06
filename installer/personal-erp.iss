; =============================================================================
; Personal ERP - Windows installer
;
; Packages the Flutter desktop release build into a single setup executable.
;
;   1. cd app_frontend && flutter build windows --release
;   2. compile this script (Inno Setup Compiler, F9 - or `iscc installer\personal-erp.iss`)
;   3. the installer lands in installer\dist\
;
; See README.md beside this file for prerequisites and the options that matter.
; =============================================================================

#define AppName        "Personal ERP"
#define AppVersion     "1.0.0"
#define AppPublisher   "Personal ERP"
#define AppUrl         "https://personal-erp-seven.vercel.app"
#define AppExeName     "personalerp_desktop.exe"

; Relative to this script. `flutter build windows` writes here; nothing else in the
; tree is packaged, because everything the app needs is already inside this folder.
#define BuildDir       "..\app_frontend\build\windows\x64\runner\Release"
#define IconFile       "..\app_frontend\windows\runner\resources\app_icon.ico"

; Fail at compile time with a sentence a human can act on. Without this, a missing
; build produces an installer that is technically valid and completely empty - which
; is only discovered on the machine you were trying to install it on.
#if !FileExists(SourcePath + BuildDir + "\" + AppExeName)
  #error Release build not found. Run: cd app_frontend && flutter build windows --release
#endif

[Setup]
; Never reuse this GUID for another product: it is the identity Windows tracks the
; install under, and it is what makes the next version replace this one in place
; rather than sitting beside it in Add/Remove Programs.
AppId={{8F3C1A72-5E4D-4B6A-9C21-7D0E5A8B4F19}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}
AppUpdatesURL={#AppUrl}
VersionInfoVersion={#AppVersion}

; `{autopf}` resolves to Program Files for an administrative install and to
; %LocalAppData%\Programs for a per-user one, so this single line covers both modes
; selected below.
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes

; **Per-user by default, with the choice offered.** The app writes nothing to its own
; directory - preferences go to %AppData% - so it does not need Program Files, and a
; default that needs no UAC prompt is one fewer reason for someone to abandon the
; install. `dialog` still lets an administrator install it for everyone.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; Flutter builds this app for x64 only. Without these two lines a 32-bit install on an
; ARM or x86 machine would succeed and then fail to launch.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; Shuts a running copy down instead of failing the file copy, which is what makes
; installing an update over a running app work.
CloseApplications=yes
RestartApplications=no

OutputDir=dist
OutputBaseFilename=PersonalERP-Setup-{#AppVersion}-x64
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}

; lzma2/max plus solid compression: `flutter_windows.dll` alone is 21 MB and is mostly
; compressible, which takes the whole payload to roughly a third of its size.
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
; Unchecked by default. An installer that litters the desktop without asking is a
; small rudeness that everyone notices.
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The entire Release folder, recursively - the .exe, flutter_windows.dll, the plugin
; DLLs, and data\ (icudtl.dat, app.so, flutter_assets). All of it is required: the app
; will not start if `data\` is missing, and the failure is a silent exit rather than an
; error message.
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; --- Visual C++ runtime -------------------------------------------------------------
; A Flutter release build links against the MSVC 2015-2022 runtime (msvcp140.dll,
; vcruntime140.dll, vcruntime140_1.dll). Practically every Windows 10/11 machine has it
; because so many applications install it - but "practically every" is not "every", and
; the failure mode is a launch that does nothing at all.
;
; To make the installer self-contained, download vc_redist.x64.exe from Microsoft into
; this folder and uncomment the two lines below.
;
; Source: "vc_redist.x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall
; (and the matching [Run] entry further down)

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
; Uncomment alongside the [Files] entry above to install the runtime first.
; Filename: "{tmp}\vc_redist.x64.exe"; Parameters: "/install /quiet /norestart"; StatusMsg: "Installing Visual C++ runtime..."; Check: not VCRedistInstalled

Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Flutter writes a small settings file next to the executable on some plugin
; configurations; remove the directory if it is empty afterwards rather than leaving a
; stub in Program Files.
Type: dirifempty; Name: "{app}"

[Code]
// True when the MSVC 2015-2022 x64 runtime is already registered. Only consulted by
// the optional vc_redist [Run] entry above; harmless when that stays commented out.
function VCRedistInstalled: Boolean;
var
  Installed: Cardinal;
begin
  Result := RegQueryDWordValue(HKLM, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Installed', Installed) and (Installed = 1);
end;
