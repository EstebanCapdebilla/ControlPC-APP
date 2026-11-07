# Compila la app Android sin Gradle (aapt2 + javac + d8 + apksigner).
# Uso:  powershell -ExecutionPolicy Bypass -File android\build.ps1
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here

$sdk = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } else { Join-Path $env:USERPROFILE 'Android\Sdk' }
$bt = Join-Path $sdk 'build-tools\36.0.0'
$jar = Join-Path $sdk 'platforms\android-34\android.jar'
if (-not (Test-Path $jar)) { throw "No se encontró el Android SDK en $sdk" }

$out = Join-Path $here 'build'
if (Test-Path $out) { Remove-Item -Recurse -Force $out }
New-Item -ItemType Directory -Force "$out\gen", "$out\classes", "$out\dex" | Out-Null

function Run($exe, [string[]]$argv) {
    $ErrorActionPreference = 'Continue'  # las advertencias de Java en stderr no son errores
    & $exe @argv 2>&1 | Where-Object { "$_".Trim() -and "$_" -notmatch '^WARNING|RemoteException|deprecat|Recompile with' } | ForEach-Object { "$_" }
    if ($LASTEXITCODE -ne 0) { throw "Falló: $exe $($argv -join ' ')" }
}

Write-Host '1/6 Recursos...'
Run "$bt\aapt2.exe" @('compile', '--dir', "$here\res", '-o', "$out\res.zip")
Run "$bt\aapt2.exe" @('link', '-o', "$out\base.apk", '-I', $jar, '--manifest', "$here\AndroidManifest.xml",
    '-A', "$here\assets", '--java', "$out\gen", '--auto-add-overlay', "$out\res.zip")

Write-Host '2/6 Compilando Java...'
$sources = @(Get-ChildItem -Recurse -Filter *.java "$here\src", "$out\gen" | ForEach-Object FullName)
Run 'javac' (@('--release', '8','-encoding', 'UTF-8', '-nowarn', '-Xlint:-options', '-classpath', $jar, '-d', "$out\classes") + $sources)

Write-Host '3/6 Convirtiendo a DEX...'
$classes = @(Get-ChildItem -Recurse -Filter *.class "$out\classes" | ForEach-Object FullName)
Run "$bt\d8.bat" (@('--release', '--min-api', '26', '--lib', $jar, '--output', "$out\dex") + $classes)

Write-Host '4/6 Empaquetando...'
Copy-Item "$out\base.apk" "$out\unsigned.apk"
$py = @"
import sys, zipfile
with zipfile.ZipFile(sys.argv[1], 'a', zipfile.ZIP_DEFLATED) as z:
    z.write(sys.argv[2], 'classes.dex')
"@
Run 'python' @('-I', '-c', $py, "$out\unsigned.apk", "$out\dex\classes.dex")
Run "$bt\zipalign.exe" @('-p', '-f', '4', "$out\unsigned.apk", "$out\aligned.apk")

Write-Host '5/6 Firmando...'
# Clave propia de este proyecto (se reutiliza para que las actualizaciones se instalen encima).
$ks = Join-Path $here 'release.keystore'
if (-not (Test-Path $ks)) {
    Run 'keytool' @('-genkeypair', '-keystore', $ks, '-storepass', 'controlpc', '-keypass', 'controlpc',
        '-alias', 'controlpc', '-keyalg', 'RSA', '-keysize', '2048', '-validity', '10000',
        '-dname', 'CN=Control PC, O=Personal')
}
$apk = Join-Path $root 'ControlPC.apk'
Run "$bt\apksigner.bat" @('sign', '--ks', $ks, '--ks-pass', 'pass:controlpc', '--key-pass', 'pass:controlpc',
    '--out', $apk, "$out\aligned.apk")

Write-Host '6/6 Verificando...'
Run "$bt\apksigner.bat" @('verify', $apk)
Remove-Item "$root\ControlPC.apk.idsig" -ErrorAction SilentlyContinue
Write-Host ("Listo: {0}  ({1:N0} KB)" -f $apk, ((Get-Item $apk).Length / 1KB))
