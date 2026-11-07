# Control Remoto PC

Usa tu celular Android como **mouse, teclado y control multimedia** de tu PC con Windows,
solo dentro de tu red Wi-Fi.

Hay dos formas de usarla desde el celular:

- **App Android** (`ControlPC.apk`): la recomendada. Agrega botones físicos de volumen, giroscopio, pantalla siempre encendida y búsqueda automática del PC.
- **Navegador** (Chrome): no hay que instalar nada, pero sin esas funciones extra.

## 1. En el PC

### Opción A: instalador (recomendada)

Ejecuta **`ControlPC-Setup.exe`** en cada Windows donde quieras usarla. No hace falta instalar Python ni nada más: el instalador trae todo.

- Instala Control PC en *Archivos de programa*, con acceso directo en el menú Inicio y desinstalador (Configuración → Aplicaciones).
- Agrega la regla del **Firewall** para redes privadas. Si compartes internet desde el celular y Windows marca esa red como *Pública*, marca la opción "Permitir también en redes públicas".
- Opcional: **iniciar con Windows**. Se puede cambiar después desde el ícono.

Control PC queda como un **ícono junto al reloj** (si no lo ves, revisa la flecha ˄ de iconos ocultos):

- **Clic**: muestra el PIN y el código QR.
- **Clic derecho**: Iniciar con Windows, Ver registro de conexiones y Salir.
- Al pasar el mouse muestra el PIN actual y cuántos celulares hay conectados.

Cada Windows tiene su propio código y su propio PIN. El celular los muestra como dos PCs distintos, aunque sean el mismo equipo.
La vinculación se guarda en `%APPDATA%\ControlPC`, así que reinstalar o actualizar no obliga a ingresar el PIN de nuevo.

### Opción B: con Python (para desarrollar)

Haz doble clic en **`Iniciar servidor.bat`** (o ejecuta `python server.py`). Necesita Python 3.8 o más nuevo.

- La primera vez, Windows preguntará por el **Firewall**: marca **Redes privadas** y pulsa *Permitir*.
- Se abre una página con el **PIN** de vinculación y un **código QR**. El PIN también aparece en la ventana del servidor.

No abras las dos opciones al mismo tiempo: las dos usan el puerto 8765.

## 2a. App Android (recomendada)

1. Pasa **`ControlPC.apk`** al celular (cable USB, Google Drive, WhatsApp a ti mismo, etc.) y ábrelo.
2. Android pedirá permiso para **instalar apps de origen desconocido**: actívalo para esa app (Archivos, Drive…) y pulsa *Instalar*.
   Play Protect puede avisar que es una app nueva: elige *Instalar de todas formas*.
3. Abre **Control PC**: buscará tu PC en la red. Tócalo e ingresa el **PIN** (solo la primera vez).

A partir de ahí, la app se conecta sola al último PC usado.

## 2b. Desde el navegador

Escanea el QR con la cámara y ábrelo en Chrome (o escribe la dirección y luego ingresa el PIN).
Para tenerla como app: menú **⋮ → Agregar a pantalla principal**.

## Funciones

| Pestaña | Qué hace |
|---|---|
| **Mouse** | Touchpad: 1 dedo mueve, toque = clic, 2 dedos = scroll (vertical y horizontal), toque con 2 dedos = clic derecho, con 3 = clic central, doble toque y arrastrar = arrastrar, mantener presionado = clic derecho. Barra de scroll en el borde derecho. Botones izquierdo / central / derecho (se pueden mantener) y 🔒 para dejar el clic presionado. **🎯 (app)**: mantenlo presionado y apunta con el celular como un puntero láser (giroscopio). |
| **Teclado** | Escritura en vivo (funciona con autocorrector y dictado por voz), Ctrl/Alt/Shift/Win fijos para combinaciones, flechas, Inicio/Fin, F1–F12, envío de textos largos y **portapapeles compartido** (celular → PC y PC → celular). |
| **Media** | Anterior / Play-Pausa / Siguiente, volumen − / silencio / + (mantén para repetir), ±5 s, Stop, pantalla completa. |
| **YT Music** | Controla YouTube Music del navegador del PC: canción actual, buscar y reproducir, cola, me gusta, volumen (necesita la extensión, ver abajo). |
| **Atajos** | Alt+Tab (sigue tocando para avanzar ventanas), escritorio, copiar/pegar/deshacer, pestañas del navegador, zoom, modo presentación, administrador de tareas, apagar pantalla, bloquear y suspender. |
| **Ajustes** | Sensibilidad del puntero (muestra cuántos píxeles mueve 1 cm de dedo), aceleración, sensibilidad de scroll, scroll natural, gestos y vibración. **En la app**: qué hacen los botones físicos de volumen, mantener la pantalla encendida, sensibilidad del giroscopio y cambiar de PC. |

## YouTube Music desde el celular

Pestaña **🎧 YT Music**: ves la canción que suena en el navegador del PC (portada, artista, progreso) y puedes:

- play/pausa, siguiente, anterior, adelantar con la barra, aleatorio y repetir
- me gusta / no me gusta y volumen de YouTube Music
- **buscar una canción y que empiece a sonar en el PC**, con su "radio" de canciones similares
- ver la **cola de reproducción** y saltar a cualquier canción

No hay que iniciar sesión en la app: se usa la sesión de YouTube Music que ya tienes abierta en el navegador del PC (tus playlists, recomendaciones y Premium). Tu cuenta nunca pasa por el celular.

### Instalar la extensión (una sola vez, en el PC)

Funciona en **Chrome** y **Edge**.

1. Abre `chrome://extensions` (en Edge: `edge://extensions`).
2. Activa **Modo de desarrollador** (arriba a la derecha en Chrome, abajo a la izquierda en Edge).
3. Pulsa **Cargar descomprimida** y elige la carpeta **`extension`** de este proyecto.
4. Abre o recarga **music.youtube.com**.

Listo: con el servidor abierto, la pestaña YT Music del celular se conecta sola. Si no ves la canción, recarga la pestaña de YouTube Music.

Notas:

- La extensión solo habla con el servidor de **tu propio PC** (`127.0.0.1`). El servidor rechaza cualquier página web que intente hacerse pasar por ella.
- Si buscas y tocas una canción sin tener YouTube Music abierto, la extensión lo abre con esa canción. Si el navegador bloquea el autoplay, toca play una vez en el PC.
- La cola se lee de la vista del reproductor de YouTube Music. Si sale vacía, en el PC toca la barra del reproductor para abrir esa vista.
- Sin Premium, el celular muestra "Anuncio" mientras suena publicidad.
- No es oficial: si Google cambia la página de YouTube Music, quizás haya que ajustar la extensión.
- En **Ajustes → App Android** puedes poner los botones físicos de volumen del celular a controlar el **volumen de YouTube Music**.

### Botones físicos de volumen (solo app)

En **Ajustes → App Android** eliges qué hacen:

- Subir / bajar el volumen del PC (por defecto)
- Subir / bajar el volumen de YouTube Music
- Canción siguiente / anterior
- Diapositiva siguiente / anterior (ideal para presentar con el celular en el bolsillo de la mano)
- Scroll arriba / abajo
- Desactivado (vuelven a controlar el volumen del celular)

Funcionan mientras la app esté abierta en pantalla. Con la app cerrada o en segundo plano, los botones vuelven a controlar el celular.

## Fluidez y baja latencia

- Conexión WebSocket directa por la red local, con el algoritmo de Nagle desactivado (`TCP_NODELAY`).
- Cada movimiento se envía al instante. Si la red se atasca, los movimientos se juntan en vez de hacer cola, así nunca se acumula retraso.
- **Suavizado** (Ajustes → Puntero): el Wi-Fi entrega los datos a tirones, y aplicarlos de golpe hace que el cursor se vea "a 30 fps". El PC reparte cada movimiento en pasos pequeños a ~500 Hz. *Medio* (16 ms) es el recomendado; *Alto* sirve si tu Wi-Fi es inestable, y *Desactivado* da la respuesta más directa.
- **App Android**: pone el Wi-Fi del celular en modo de baja latencia mientras la app está en pantalla (sin agrupar paquetes para ahorrar batería) y usa la frecuencia más alta de la pantalla (90/120 Hz) para leer el dedo más seguido.
- La barra superior muestra la latencia en ms. Para la mínima: Wi-Fi de 5 GHz y, si puedes, el PC conectado por cable al router.
- Si el PC es un portátil con batería, Windows también puede ahorrar energía en el Wi-Fi. Conectarlo al cargador o elegir el modo de energía **Mejor rendimiento** ayuda.

## Seguridad

- El servidor **solo acepta conexiones de la red local** (IPs privadas). Las de Internet se rechazan.
- Para conectarse hace falta el **código de acceso** del PC. Se obtiene con el **PIN de 6 dígitos**, que cambia cada vez que inicias el servidor. Tras 5 PIN incorrectos desde un mismo equipo se bloquean sus intentos 60 segundos, y tras 30 incorrectos en total se genera un PIN nuevo.
- **La app Android verifica al PC antes de entregarle el código**: el PC tiene que demostrar que lo conoce, sin enviarlo. Si otro equipo de la red se hace pasar por tu PC o toma su IP, la app no le manda nada y te avisa.
- Solo se aceptan pedidos dirigidos a la IP del PC o a `localhost`. Así una página web abierta en el PC no puede leer el PIN ni el código.
- Si el celular deja de responder 10 segundos (por ejemplo, se cortó el Wi-Fi), el PC cierra la conexión y **suelta cualquier clic que estuviera presionado**.
- La conexión no va cifrada (HTTP en la red local). En una Wi-Fi con contraseña o en el punto de acceso de tu celular está protegida por la red. En una Wi-Fi abierta, alguien cercano podría ver el código.
- Para desvincular **todos** los celulares: `python server.py --new-token`.

## Opciones del servidor

```
python server.py --no-browser   # no abrir la página del PIN/QR
python server.py --port 9000    # usar otro puerto (por defecto 8765; la búsqueda automática usa UDP 8766)
python server.py --new-token    # generar un código de acceso nuevo
```

## Problemas comunes

- **La app no encuentra el PC**: revisa que el servidor esté abierto, que ambos estén en la misma Wi-Fi y que el Firewall permita Python en *redes privadas*. En Windows, la red Wi-Fi debe estar marcada como **Privada** (Configuración → Red e Internet → Wi-Fi → tu red). Si sigue sin aparecer, usa **Conectar por IP** con la dirección que muestra el servidor.
- Algunas redes de invitados o públicas aíslan a los dispositivos entre sí: ahí no funcionará.
- **No controla ciertas ventanas** (Administrador de tareas, programas abiertos como administrador): ejecuta el servidor como administrador.
- **El QR no aparece**: recarga la página (clic en el ícono). Si sigue sin aparecer, usa el PIN o escribe la dirección.
- **"No pudo demostrar que es tu PC"** (app Android): el PC cambió su código (`--new-token`, otro Windows o se borró `%APPDATA%\ControlPC`) o hay otro equipo en esa IP. Toca ✕ en ese PC para olvidarlo y vincúlalo de nuevo con el PIN.
- **Iniciar con Windows**: con el instalador, clic derecho en el ícono → *Iniciar con Windows*. Con Python: presiona `Win + R`, escribe `shell:startup` y pon ahí un acceso directo a `Iniciar servidor.bat`.

## Recompilar el instalador de Windows

Si cambias `server.py`, `tray.py`, `web/` o `extension/`:

```
powershell -ExecutionPolicy Bypass -File installer\build-installer.ps1
```

Genera `ControlPC-Setup.exe`. Solo en el PC que compila hace falta **Inno Setup 6** (`winget install JRSoftware.InnoSetup`). El Python embebido se descarga solo en `installer\cache`.
Para cambiar el ícono: edita `installer\make_icon.py` y ejecútalo (usa Pillow).

## Recompilar la app Android

Si cambias algo en `android/`:

```
powershell -ExecutionPolicy Bypass -File android\build.ps1
```

Necesita el Android SDK en `C:\Users\<tu usuario>\Android\Sdk` (platform 34 y build-tools 36) y Java.
**Guarda `android/release.keystore`**: es la firma de la app. Si la pierdes, las versiones nuevas no se podrán instalar encima de la anterior (habría que desinstalarla primero).

La interfaz (pestañas, botones, ajustes) vive en la carpeta `web/` y la sirve el PC, así que los cambios ahí **no necesitan recompilar el APK**.
