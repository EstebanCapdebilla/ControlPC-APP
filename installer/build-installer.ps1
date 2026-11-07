# Crea ControlPC-Setup.exe (instalador de Windows con Python incluido).
# Uso:  powershell -ExecutionPolicy Bypass -File installer\build-installer.ps1
# Necesita (solo en el PC que compila): Inno Setup 6 y el Python embebido en installer\cache.
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
$pyVer = '3.13.15'
$zip = Join-Path $here "cache\python-$pyVer-embed-amd64.zip"
$stage = Join-Path $root 'build\stage'

if (-not (Test-Path $zip)) {
    Write-Host "Descargando Python $pyVer embebido..."
    New-Item -ItemType Directory -Force (Split-Path $zip) | Out-Null
    Invoke-WebRequest "https://www.python.org/ftp/python/$pyVer/python-$pyVer-embed-amd64.zip" -OutFile $zip
}
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw 'No se encontró Inno Setup 6. Instálalo con:  winget install JRSoftware.InnoSetup' }

Write-Host '1/3 Preparando archivos...'
if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
New-Item -ItemType Directory -Force $stage | Out-Null
foreach ($f in 'server.py', 'tray.py', 'icon.ico', 'LEEME.md', 'ControlPC.apk') { Copy-Item (Join-Path $root $f) $stage }
Copy-Item -Recurse (Join-Path $root 'web') (Join-Path $stage 'web')
Copy-Item -Recurse (Join-Path $root 'extension') (Join-Path $stage 'extension')

Write-Host '2/3 Agregando Python...'
$py = Join-Path $stage 'python'
Expand-Archive -Path $zip -DestinationPath $py
# El Python embebido solo busca módulos donde dice su archivo ._pth: se agrega la carpeta del programa.
$pth = Get-ChildItem $py -Filter 'python*._pth' | Select-Object -First 1
Add-Content -Path $pth.FullName -Value '..' -Encoding ascii

Write-Host '3/3 Compilando instalador...'
# Se compila en build\out y luego se copia: a veces el antivirus revisa el .exe mientras se
# escribe y Inno Setup falla ("EndUpdateResource failed"). En ese caso se reintenta.
$built = Join-Path $root 'build\out\ControlPC-Setup.exe'
for ($try = 1; $try -le 4; $try++) {
    & $iscc /Q (Join-Path $here 'ControlPC.iss')
    if ($LASTEXITCODE -eq 0) { break }
    if ($try -eq 4) { throw 'Falló Inno Setup' }
    Write-Host "   Reintentando ($try)..."
    Start-Sleep -Seconds 3
}
$out = Join-Path $root 'ControlPC-Setup.exe'
Copy-Item $built $out -Force
Write-Host ("Listo: {0}  ({1:N1} MB)" -f $out, ((Get-Item $out).Length / 1MB))
