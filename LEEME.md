> **Respaldo de la versión 1 (solo navegador).** Funciona sola: abre `Iniciar servidor.bat` desde esta carpeta.
> No la abras al mismo tiempo que la versión nueva, porque las dos usan el puerto 8765.

# Control Remoto PC

Usa tu celular Android como **mouse, teclado y control multimedia** de tu PC con Windows,
solo dentro de tu red Wi-Fi.

## Cómo usarla

1. En el PC, haz doble clic en **`Iniciar servidor.bat`** (o ejecuta `python server.py`).
   - La primera vez, Windows preguntará por el **Firewall**: marca **Redes privadas** y pulsa *Permitir*.
   - Se abrirá una página con un **código QR**.
2. Con el celular en la **misma red Wi-Fi**, escanea el QR con la cámara y ábrelo en Chrome.
3. En Chrome: menú **⋮ → Agregar a pantalla principal**. Ya la tienes como app con su icono.

La próxima vez solo inicia el servidor en el PC y abre la app desde el celular: se reconecta sola.

No hay que instalar nada: el servidor usa solo Python (3.8 o más nuevo).

## Funciones

| Pestaña | Qué hace |
|---|---|
| **Mouse** | Touchpad: 1 dedo mueve, toque = clic, 2 dedos = scroll (vertical y horizontal), toque con 2 dedos = clic derecho, con 3 = clic central, doble toque y arrastrar = arrastrar, mantener presionado = clic derecho. Barra de scroll en el borde derecho. Botones izquierdo / central / derecho (se pueden mantener) y 🔒 para dejar el clic presionado. |
| **Teclado** | Escritura en vivo (funciona con autocorrector y dictado por voz), Ctrl/Alt/Shift/Win fijos para combinaciones, flechas, Inicio/Fin, F1–F12 y envío de textos largos. |
| **Media** | Anterior / Play-Pausa / Siguiente, volumen − / silencio / + (mantén para repetir), ±5 s, Stop, pantalla completa. |
| **Atajos** | Alt+Tab (mantén tocando para avanzar ventanas), escritorio, copiar/pegar/deshacer, pestañas del navegador, zoom, modo presentación (diapositivas), administrador de tareas, apagar pantalla, bloquear y suspender. |
| **Ajustes** | Sensibilidad del puntero (muestra cuántos píxeles mueve 1 cm de dedo), aceleración, sensibilidad de scroll, scroll natural, gestos y vibración. Se guardan en el celular. |

En la barra superior ves si está conectado y la **latencia** en milisegundos.

## Baja latencia

- Conexión WebSocket directa en la red local con el algoritmo de Nagle desactivado (`TCP_NODELAY`).
- El movimiento se envía en cada evento táctil; si la red se atasca, los movimientos se juntan en vez de quedar en cola (así nunca se siente un "retraso acumulado").
- Para menor latencia: usa Wi-Fi de 5 GHz y conecta el PC por cable al router si puedes.

## Seguridad

- El servidor **solo acepta conexiones de la red local** (IPs privadas); conexiones desde Internet se rechazan.
- Cada PC tiene un **código de acceso** (incluido en el QR). Sin él, nadie de tu red puede controlarlo.
- Para invalidar el código y desvincular todos los celulares: `python server.py --new-token`.

## Opciones del servidor

```
python server.py --no-browser   # no abrir la página del QR
python server.py --port 9000    # usar otro puerto (por defecto 8765)
python server.py --new-token    # generar un código nuevo
```

## Problemas comunes

- **No conecta**: revisa que ambos estén en la misma Wi-Fi, que el Firewall permita Python en redes privadas, y que la red Wi-Fi esté marcada como *Privada* en Windows. Algunas redes públicas/de invitados aíslan a los dispositivos entre sí.
- **El QR no aparece**: la página necesita Internet para dibujarlo; escribe la dirección que muestra en el celular.
- **No controla ciertas ventanas** (p. ej. Administrador de tareas o programas como administrador): ejecuta el servidor como administrador.
- **Iniciar con Windows**: presiona `Win + R`, escribe `shell:startup` y pon ahí un acceso directo a `Iniciar servidor.bat`.
