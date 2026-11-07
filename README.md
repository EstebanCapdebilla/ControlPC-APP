# Control PC

Usa tu celular Android como **mouse, teclado, control multimedia y control de YouTube Music** de tu PC con Windows, dentro de tu red Wi-Fi.

## Descargar

En **[Releases](../../releases/latest)**:

- `ControlPC-Setup.exe`: instalador para Windows (trae Python incluido, no hay que instalar nada más).
- `ControlPC.apk`: app para el celular Android.

La guía completa (instalación, funciones, extensión de YouTube Music, seguridad y cómo compilar) está en **[LEEME.md](LEEME.md)**.

## Versiones

| Versión | Qué trajo |
|---|---|
| v2.2 | Listas de reproducción de YouTube Music (completas, con buscador), botón para abrir YouTube Music desde el celular |
| v2.1 | Instalador de Windows con ícono en la bandeja, QR sin internet y correcciones de seguridad (verificación del PC en la app, protección contra DNS rebinding, clic que quedaba presionado) |
| v2.0 | App Android, vinculación con PIN, portapapeles compartido, control de YouTube Music con extensión, suavizado del puntero |
| v1.0 | Primera versión: solo desde el navegador del celular |

Para ver el código de una versión anterior: pestaña **Tags** del repositorio, o `git checkout v1.0`.

## Estructura

```
server.py         servidor del PC (solo librería estándar de Python)
tray.py           ícono en la bandeja de Windows
web/              interfaz que se muestra en el celular (la sirve el PC)
android/          app Android (contenedor nativo de la interfaz web)
extension/        extensión de Chrome/Edge para YouTube Music
installer/        script del instalador (Inno Setup) e ícono
```
