; Instalador de Control PC (servidor para Windows).
; Se compila con installer\build-installer.ps1, que prepara la carpeta "stage".

#define AppName "Control PC"
#define AppVersion "2.0.0"
#define Stage "..\build\stage"

[Setup]
AppId={{6B0E3C9A-6E1F-4C55-9E62-0C7A5D3B9F21}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Control PC
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Necesita administrador para instalar en "Archivos de programa" y crear la regla del Firewall.
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=../build/out
OutputBaseFilename=ControlPC-Setup
SetupIconFile=..\icon.ico
UninstallDisplayIcon={app}\icon.ico
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"
Name: "autostart"; Description: "Iniciar Control PC con Windows (queda junto al reloj)"; GroupDescription: "Inicio:"
Name: "fwpublic"; Description: "Permitir también en redes públicas (por ejemplo, si Windows marca así el punto de acceso de tu celular)"; GroupDescription: "Firewall de Windows:"; Flags: unchecked

[Files]
Source: "{#Stage}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\server.py"" --tray"; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"; Comment: "Controla este PC desde el celular"
Name: "{group}\Extensión de YouTube Music (carpeta)"; Filename: "{app}\extension"
Name: "{group}\Léeme"; Filename: "{app}\LEEME.md"
Name: "{group}\Desinstalar {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\server.py"" --tray"; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "ControlPC"; ValueData: """{app}\python\pythonw.exe"" ""{app}\server.py"" --tray --no-browser"; Tasks: autostart; Flags: uninsdeletevalue

[Run]
; Regla del Firewall para el Python incluido (TCP 8765 y UDP 8766 para la búsqueda automática).
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#AppName}"""; Flags: runhidden waituntilterminated
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""{#AppName}"" dir=in action=allow program=""{app}\python\pythonw.exe"" enable=yes profile=private"; Flags: runhidden waituntilterminated; Tasks: not fwpublic
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""{#AppName}"" dir=in action=allow program=""{app}\python\pythonw.exe"" enable=yes profile=private,public"; Flags: runhidden waituntilterminated; Tasks: fwpublic
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\server.py"" --tray"; WorkingDir: "{app}"; Description: "Abrir Control PC ahora"; Flags: postinstall nowait skipifsilent runasoriginaluser

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#AppName}"""; Flags: runhidden waituntilterminated; RunOnceId: "fw"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\__pycache__"

[Code]
{ Cierra el servidor si está abierto (para poder reemplazar o borrar sus archivos). }
procedure StopServer();
var
  Code: Integer;
begin
  Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -NonInteractive -Command "Get-Process pythonw,python -ErrorAction SilentlyContinue | ' +
    'Where-Object { $_.Path -like ''' + ExpandConstant('{app}') + '\*'' } | Stop-Process -Force"',
    '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopServer();
  Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  StopServer();
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    if MsgBox('¿Borrar también la vinculación con tus celulares y el registro de conexiones?' + #13#10 +
              '(Si vas a reinstalar, elige No y no tendrás que volver a ingresar el PIN.)',
              mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(ExpandConstant('{userappdata}\ControlPC'), True, True, True);
end;
