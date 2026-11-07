'use strict';
/* Control Remoto PC - cliente del celular */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

/* ------------------------------------------------------------------ almacenamiento */
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* sin almacenamiento */ } },
  del(k) { try { localStorage.removeItem(k); } catch { /* */ } },
};

/* ------------------------------------------------------------------ token de acceso */
const qs = new URLSearchParams(location.search);
let token = qs.get('t') || store.get('rc_token') || '';
if (qs.get('t')) {
  store.set('rc_token', token);
  history.replaceState(null, '', location.pathname); // quita el código de la barra
}

/* ------------------------------------------------------------------ ajustes */
/* Dentro de la app Android existe window.AndroidRC (funciones nativas extra). */
const NATIVE = window.AndroidRC || null;

const DEFAULTS = {
  sens: 1.6, accel: 0.6, scroll: 1.5, natural: true, tap: true, longpress: true, strip: true, haptic: true,
  hwvol: 'volume', awake: true, gyro: 1.2, smooth: 16,
};
let S = { ...DEFAULTS };
try { Object.assign(S, JSON.parse(store.get('rc_settings') || '{}')); } catch { /* */ }
const saveSettings = () => store.set('rc_settings', JSON.stringify(S));

const buzz = (p = 8) => {
  if (!S.haptic) return;
  try {
    if (NATIVE) NATIVE.vibrate(Array.isArray(p) ? p.filter((_, i) => i % 2 === 0).reduce((a, b) => a + b, 0) : p);
    else if (navigator.vibrate) navigator.vibrate(p);
  } catch { /* */ }
};

function applyNative() {
  if (!NATIVE) return;
  NATIVE.setCaptureVolume(S.hwvol !== 'off');
  NATIVE.setKeepAwake(!!S.awake);
}

/* ------------------------------------------------------------------ conexión */
let ws = null, retry = 0, retryTimer = null;

function setStatus(state, text) {
  const dot = $('#dot');
  dot.className = 'dot' + (state === 'ok' ? ' ok' : state === 'bad' ? ' bad' : '');
  $('#status').textContent = text;
}

function showOverlay(title, text, askPin = false) {
  $('#ov-title').textContent = title;
  $('#ov-text').textContent = text;
  $('#ov-pin').hidden = !askPin;
  $('#ov-retry').hidden = askPin;
  $('#ov-home').hidden = !NATIVE;
  $('#pin-error').textContent = '';
  $('#overlay').classList.remove('hidden');
  if (askPin) setTimeout(() => $('#pin').focus(), 100);
}
const hideOverlay = () => $('#overlay').classList.add('hidden');

function askPin(title) {
  setStatus('bad', 'Sin vincular');
  showOverlay(title, 'Ingresa el PIN de 6 dígitos que aparece en la pantalla del PC (en la ventana del servidor o en la página que se abrió).', true);
}

async function submitPin() {
  const pin = $('#pin').value.replace(/\D/g, '');
  if (pin.length !== 6) { $('#pin-error').textContent = 'El PIN tiene 6 dígitos.'; return; }
  $('#pin-go').disabled = true;
  try {
    const r = await fetch('/api/pair?pin=' + pin, { cache: 'no-store' });
    const j = await r.json();
    if (!r.ok || !j.token) throw new Error(j.error || 'PIN incorrecto');
    token = j.token;
    store.set('rc_token', token);
    $('#pin').value = '';
    hideOverlay();
    buzz(20);
    retry = 0;
    connect();
  } catch (err) {
    $('#pin-error').textContent = err.message || 'No se pudo vincular';
    buzz([30, 50, 30]);
  } finally {
    $('#pin-go').disabled = false;
  }
}
$('#pin-go').addEventListener('click', submitPin);
$('#pin').addEventListener('keydown', (e) => { if (e.key === 'Enter') submitPin(); });
$('#pin').addEventListener('input', () => { if ($('#pin').value.replace(/\D/g, '').length === 6) submitPin(); });
$('#ov-home').addEventListener('click', () => NATIVE && NATIVE.home());

function connect() {
  clearTimeout(retryTimer);
  if (ws && ws.readyState <= 1) return;
  if (!token) { askPin('Vincular con el PC'); return; }
  setStatus('wait', 'Conectando…');
  const sock = new WebSocket(`ws://${location.host}/ws?t=${encodeURIComponent(token)}`);
  ws = sock;
  sock.onopen = () => {
    retry = 0;
    setStatus('ok', 'Conectado');
    hideOverlay();
    sendConfig();
    ping();
  };
  sock.onmessage = (e) => {
    let m; try { m = JSON.parse(e.data); } catch { return; }
    if (m[0] === 'p') $('#latency').textContent = Math.round(performance.now() - m[1]) + ' ms';
    else if (m[0] === 'hello') {
      $('#pcname').textContent = '· ' + m[1];
      if (NATIVE) NATIVE.remember(m[2] || '', m[1], location.hostname, parseInt(location.port, 10) || 80, token);
    } else if (m[0] === 'clip') receiveClipboard(m[1]);
    else if (m[0] === 'ytm') onYtm(m[1], m[2]);
  };
  sock.onclose = (e) => {
    if (ws === sock) ws = null;
    $('#latency').textContent = '';
    if (e.code === 4001) {
      token = '';
      store.del('rc_token');
      askPin('Vincular de nuevo');
      return;
    }
    setStatus('bad', 'Desconectado');
    if (retry > 3) showOverlay('Sin conexión', 'Revisa que el servidor siga abierto en el PC y que ambos estén en la misma red Wi-Fi.');
    retryTimer = setTimeout(connect, Math.min(3000, 250 * 2 ** retry++));
  };
}

function send(arr) {
  if (ws && ws.readyState === 1) { ws.send(JSON.stringify(arr)); return true; }
  return false;
}
function ping() { send(['p', performance.now()]); }
function sendConfig() { send(['cfg', { smooth: S.smooth }]); }
setInterval(ping, 2000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) { retry = 0; connect(); } });
$('#ov-retry').addEventListener('click', () => { retry = 0; hideOverlay(); connect(); });

/* --------------------------------- envío de movimiento con baja latencia
   Se acumula la parte fraccionaria para no perder precisión y, si la red se
   atasca (bufferedAmount), se agrupan los deltas en vez de hacer cola. */
const acc = { mx: 0, my: 0, fx: 0, fy: 0, sv: 0, sh: 0, fsv: 0, fsh: 0, scheduled: false };

function flush() {
  if (!ws || ws.readyState !== 1) { acc.mx = acc.my = acc.sv = acc.sh = 0; return; }
  if (ws.bufferedAmount > 512) {
    if (!acc.scheduled) { acc.scheduled = true; setTimeout(() => { acc.scheduled = false; flush(); }, 4); }
    return;
  }
  if (acc.mx || acc.my) { ws.send(`["m",${acc.mx},${acc.my}]`); acc.mx = acc.my = 0; }
  if (acc.sv || acc.sh) { ws.send(`["s",${acc.sv},${acc.sh}]`); acc.sv = acc.sh = 0; }
}
function queueMove(dx, dy) {
  acc.fx += dx; acc.fy += dy;
  const ix = Math.trunc(acc.fx), iy = Math.trunc(acc.fy);
  acc.fx -= ix; acc.fy -= iy;
  acc.mx += ix; acc.my += iy;
  if (ix || iy) flush();
}
function queueScroll(v, h) {
  acc.fsv += v; acc.fsh += h;
  const iv = Math.trunc(acc.fsv), ih = Math.trunc(acc.fsh);
  acc.fsv -= iv; acc.fsh -= ih;
  acc.sv += iv; acc.sh += ih;
  if (iv || ih) flush();
}

/* ------------------------------------------------------------------ touchpad */
const pad = $('#pad');
const TAP_MS = 260, TAP_SLOP = 9, DOUBLE_MS = 300, LONG_MS = 550, STRIP_W = 46;
let g = null;            // gesto en curso
let lastTap = { t: -1e9, x: 0, y: 0 };
let dragLocked = false;

function onStart(e) {
  e.preventDefault();
  const t0 = e.changedTouches[0];
  if (!g) {
    const r = pad.getBoundingClientRect();
    const inStrip = S.strip && t0.clientX > r.right - STRIP_W;
    g = {
      start: e.timeStamp, lastT: e.timeStamp, max: 0, dist: 0, moved: false,
      mode: inStrip ? 'strip' : 'move', drag: false, long: false, pts: new Map(), longTimer: null, speed: 0,
    };
    // doble toque y mantener = arrastrar
    if (!inStrip && S.tap && e.timeStamp - lastTap.t < DOUBLE_MS &&
        Math.hypot(t0.clientX - lastTap.x, t0.clientY - lastTap.y) < 45) {
      g.drag = true;
      send(['d', 'l']);
      buzz(12);
    } else if (!inStrip && S.longpress) {
      g.longTimer = setTimeout(() => {
        if (g && !g.moved && g.max === 1) { g.long = true; send(['c', 'r']); buzz([15, 40, 15]); }
      }, LONG_MS);
    }
    pad.classList.add('touching');
  }
  for (const t of e.changedTouches) g.pts.set(t.identifier, { x: t.clientX, y: t.clientY });
  g.max = Math.max(g.max, e.touches.length);
  if (e.touches.length >= 2 && g.mode === 'move' && !g.drag) g.mode = 'scroll';
  if (g.max > 1) clearTimeout(g.longTimer);
}

function onMove(e) {
  e.preventDefault();
  if (!g) return;
  let sx = 0, sy = 0, n = 0;
  for (const t of e.touches) {
    const p = g.pts.get(t.identifier);
    if (!p) continue;
    sx += t.clientX - p.x; sy += t.clientY - p.y; n++;
    p.x = t.clientX; p.y = t.clientY;
    if (g.mode === 'move') break; // en modo mover solo cuenta el primer dedo
  }
  if (!n) return;
  const dx = sx / n, dy = sy / n;
  const d = Math.hypot(dx, dy);
  const dt = Math.max(1, e.timeStamp - g.lastT);
  g.lastT = e.timeStamp;
  g.dist += d;
  if (!g.moved && g.dist > TAP_SLOP) { g.moved = true; clearTimeout(g.longTimer); }
  if (g.long) return;

  if (g.mode === 'move') {
    // Velocidad promediada: los eventos táctiles llegan a intervalos irregulares y
    // sin promedio la aceleración cambiaría a tirones entre un evento y otro.
    g.speed += (Math.min(d / dt, 4) - g.speed) * 0.35; // px por ms
    const gain = S.sens * (1 + S.accel * g.speed);
    queueMove(dx * gain, dy * gain);
  } else {
    // 120 = un "paso" de rueda. 40 px de dedo con sensibilidad 1 = 1 paso.
    const k = S.scroll * 3 * (S.natural ? 1 : -1);
    queueScroll(dy * k, g.mode === 'scroll' ? -dx * k : 0);
  }
}

function onEnd(e) {
  e.preventDefault();
  if (!g) return;
  for (const t of e.changedTouches) g.pts.delete(t.identifier);
  if (e.touches.length > 0) return;
  clearTimeout(g.longTimer);
  pad.classList.remove('touching');
  const dur = e.timeStamp - g.start;
  const t = e.changedTouches[0];
  if (g.drag) {
    send(['u', 'l']);
    lastTap.t = -1e9;
  } else if (!g.moved && !g.long && dur < TAP_MS + (g.max > 1 ? 80 : 0) && S.tap && e.type !== 'touchcancel') {
    if (g.max === 1) {
      send(['c', 'l']);
      lastTap = { t: e.timeStamp, x: t.clientX, y: t.clientY };
      buzz(8);
    } else if (g.max === 2) {
      send(['c', 'r']); buzz([10, 30, 10]);
    } else {
      send(['c', 'm']); buzz([10, 30, 10, 30, 10]);
    }
  }
  g = null;
}

pad.addEventListener('touchstart', onStart, { passive: false });
pad.addEventListener('touchmove', onMove, { passive: false });
pad.addEventListener('touchend', onEnd, { passive: false });
pad.addEventListener('touchcancel', onEnd, { passive: false });

/* botones del mouse: presionar / soltar (permite arrastrar con otro dedo) */
$$('[data-hold]').forEach((b) => {
  const btn = b.dataset.hold;
  let down = false;
  b.addEventListener('pointerdown', (e) => { e.preventDefault(); down = true; b.classList.add('pressed'); send(['d', btn]); buzz(); });
  const up = () => { if (!down) return; down = false; b.classList.remove('pressed'); send(['u', btn]); };
  ['pointerup', 'pointercancel', 'pointerleave'].forEach((ev) => b.addEventListener(ev, up));
  b.addEventListener('contextmenu', (e) => e.preventDefault());
});
$('#draglock').addEventListener('click', () => {
  dragLocked = !dragLocked;
  send([dragLocked ? 'd' : 'u', 'l']);
  $('#draglock').classList.toggle('on', dragLocked);
  buzz(15);
});

/* ------------------------------------------------------------------ modificadores */
const mods = new Set();
function takeMods() { const m = [...mods]; mods.clear(); $$('.mod').forEach((b) => b.classList.remove('on')); return m; }
$$('.mod').forEach((b) => b.addEventListener('click', () => {
  const m = b.dataset.mod;
  if (mods.has(m)) mods.delete(m); else mods.add(m);
  b.classList.toggle('on', mods.has(m));
  buzz();
}));

/* ------------------------------------------------------------------ botones genéricos */
function holdRepeat(el, fn) {
  let t1 = null, t2 = null;
  const stop = () => { clearTimeout(t1); clearInterval(t2); el.classList.remove('pressed'); };
  el.addEventListener('pointerdown', (e) => {
    e.preventDefault(); stop(); el.classList.add('pressed');
    fn(); buzz();
    t1 = setTimeout(() => { t2 = setInterval(fn, 70); }, 380);
  });
  ['pointerup', 'pointercancel', 'pointerleave'].forEach((ev) => el.addEventListener(ev, stop));
  el.addEventListener('contextmenu', (e) => e.preventDefault());
}

function actionFor(b) {
  const inKeyboard = !!b.closest('#tab-keys');
  if (b.dataset.key) return () => send(['k', [...(inKeyboard ? takeMods() : []), b.dataset.key]]);
  if (b.dataset.combo) return () => send(['k', b.dataset.combo.split('+').map((k) => k || '+')]);
  if (b.dataset.sys) return () => send(['sys', b.dataset.sys]);
  return null;
}

// F1..F12
$('#fkeys').innerHTML = Array.from({ length: 12 }, (_, i) => `<button data-key="f${i + 1}">F${i + 1}</button>`).join('');

$$('[data-key],[data-combo],[data-sys]').forEach((b) => {
  const fn = actionFor(b);
  if (!fn) return;
  if (b.hasAttribute('data-repeat')) return holdRepeat(b, fn);
  b.addEventListener('click', () => {
    if (b.dataset.confirm && !confirm(b.dataset.confirm)) return;
    fn(); buzz();
  });
});

/* Alt+Tab que mantiene Alt mientras sigas tocando */
$('#alttab').addEventListener('click', () => { send(['at', 0]); buzz(); });
$('#alttab-back').addEventListener('click', () => { send(['at', 1]); buzz(); });

/* ------------------------------------------------------------------ escritura en vivo
   Se compara el texto anterior con el nuevo (sirve con Gboard, autocorrector y
   dictado por voz): se borran los caracteres que cambiaron y se envían los nuevos. */
const live = $('#live');
let prev = '';
live.addEventListener('input', () => {
  const v = live.value;
  let p = 0;
  const m = Math.min(prev.length, v.length);
  while (p < m && prev[p] === v[p]) p++;
  const del = prev.length - p;
  const add = v.slice(p);
  if (del > 0) send(['r', 'backspace', del]);
  if (add) {
    if (mods.size) {
      send(['k', [...takeMods(), add[0]]]);
      if (add.length > 1) send(['t', add.slice(1)]);
    } else {
      send(['t', add]);
    }
  }
  prev = v;
  if (v.length > 300 && v.endsWith(' ')) { live.value = ''; prev = ''; }
});
live.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') { e.preventDefault(); send(['k', [...takeMods(), 'enter']]); live.value = ''; prev = ''; }
  else if (e.key === 'Backspace' && live.value === '') { send(['k', ['backspace']]); }
});

function sendBulk(enter) {
  const el = $('#bulk');
  if (!el.value) return;
  send(['t', el.value + (enter ? '\n' : '')]);
  el.value = '';
  buzz(15);
}
$('#bulk-send').addEventListener('click', () => sendBulk(false));
$('#bulk-send-enter').addEventListener('click', () => sendBulk(true));

/* ------------------------------------------------------------------ portapapeles */
$('#clip-to-pc').addEventListener('click', () => {
  // En el navegador (http) no se puede leer el portapapeles: se usa el cuadro de texto.
  const text = NATIVE ? NATIVE.paste() : $('#bulk').value;
  if (!text) {
    $('#clip-note').textContent = NATIVE ? 'Tu portapapeles está vacío.' : 'Pega el texto en "Enviar texto largo" y vuelve a tocar.';
    return;
  }
  send(['cs', text]);
  $('#clip-note').textContent = `Listo: ${text.length} caracteres en el portapapeles del PC.`;
  buzz(15);
});
$('#clip-from-pc').addEventListener('click', () => send(['cg']));
function receiveClipboard(text) {
  if (!text) { $('#clip-note').textContent = 'El portapapeles del PC está vacío.'; return; }
  if (NATIVE) {
    NATIVE.copy(text);
    $('#clip-note').textContent = `Copiado al celular (${text.length} caracteres).`;
  } else {
    const el = $('#bulk');
    el.value = text;
    el.closest('details').open = true;
    el.focus(); el.select();
    $('#clip-note').textContent = 'Texto del PC puesto en el cuadro de arriba: mantén presionado para copiarlo.';
  }
  buzz(15);
}

/* ------------------------------------------------------------------ funciones nativas */
// Botones físicos de volumen (la app nativa llama a esta función)
window.rcHardwareKey = (dir, repeat) => {
  const up = dir === 'up';
  switch (S.hwvol) {
    case 'volume': send(['k', [up ? 'volup' : 'voldown']]); break;
    case 'media': if (!repeat) send(['k', [up ? 'next' : 'prev']]); break;
    case 'slides': if (!repeat) send(['k', [up ? 'right' : 'left']]); break;
    case 'scroll': queueScroll(up ? 120 : -120, 0); break;
    case 'ytmvol': ytmVolumeStep(up ? 5 : -5); break;
    default: return;
  }
  if (!repeat) buzz(6);
};

// Giroscopio: radianes girados desde el último evento
window.rcGyro = (dx, dy) => {
  const k = S.gyro * 1400;
  queueMove(dx * k, dy * k);
};
if (NATIVE && NATIVE.hasGyro()) {
  const gb = $('#gyro');
  gb.hidden = false;
  const on = (e) => { e.preventDefault(); NATIVE.gyro(true); gb.classList.add('on'); buzz(10); };
  const off = () => { NATIVE.gyro(false); gb.classList.remove('on'); };
  gb.addEventListener('pointerdown', on);
  ['pointerup', 'pointercancel', 'pointerleave'].forEach((ev) => gb.addEventListener(ev, off));
  gb.addEventListener('contextmenu', (e) => e.preventDefault());
}

/* ------------------------------------------------------------------ YouTube Music
   El celular habla con la extensión del navegador del PC a través del servidor. */
const ytm = { ext: false, state: null, stateAt: 0, seq: 0, pending: new Map(), seeking: false, volTimer: null, lastArt: '' };
const escHtml = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmtTime = (s) => { s = Math.max(0, Math.floor(s || 0)); const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = String(s % 60).padStart(2, '0'); return h ? `${h}:${String(m).padStart(2, '0')}:${x}` : `${m}:${x}`; };

function ytmCmd(cmd, args = {}) {
  return new Promise((resolve) => {
    const id = ++ytm.seq;
    ytm.pending.set(id, resolve);
    if (!send(['ytm', { id, cmd, args }])) { ytm.pending.delete(id); resolve({ error: 'offline' }); return; }
    setTimeout(() => { if (ytm.pending.has(id)) { ytm.pending.delete(id); resolve({ error: 'timeout' }); } }, 12000);
  });
}
function ytmError(r) {
  const msg = {
    noext: 'La extensión no está conectada en el PC.',
    notab: 'YouTube Music no está abierto en el PC.',
    offline: 'Sin conexión con el PC.',
    timeout: 'El PC no respondió a tiempo.',
  }[r.error] || r.error;
  $('#ytm-note').textContent = msg;
  if (r.error === 'notab') { ytm.state = null; renderYtm(); }
}

function onYtm(kind, data) {
  if (kind === 'ext') { ytm.ext = !!data; if (!data) ytm.state = null; renderYtm(); }
  else if (kind === 'state') { ytm.state = data; ytm.stateAt = performance.now(); renderYtm(); }
  else if (kind === 'res') { const r = ytm.pending.get(data.id); if (r) { ytm.pending.delete(data.id); r(data); } }
}

function ytmNow() {
  const s = ytm.state;
  if (!s) return 0;
  const t = s.time + (s.playing ? (performance.now() - ytm.stateAt) / 1000 : 0);
  return s.duration ? Math.min(t, s.duration) : t;
}

function renderYtm() {
  const s = ytm.state;
  $('#ytm-noext').hidden = ytm.ext;
  $('#ytm-notab').hidden = !ytm.ext || !!s;
  $('#ytm-player').hidden = !ytm.ext || !s;
  if (!s) return;
  const has = !!s.ready;
  $('#ytm-title').textContent = !has ? 'Nada sonando' : s.ad ? 'Anuncio' : (s.title || 'Sin título');
  $('#ytm-artist').textContent = !has ? 'Busca una canción abajo'
    : s.ad ? 'Tu canción empieza después del anuncio' : [s.artist, s.album].filter(Boolean).join(' • ');
  if (s.art !== ytm.lastArt) { ytm.lastArt = s.art; $('#ytm-art').src = s.art || 'icon.svg'; }
  $('#ytm-pp').textContent = s.playing ? '⏸' : '▶';
  $('#ytm-like').classList.toggle('on', s.like === 'LIKE');
  $('#ytm-dislike').classList.toggle('on', s.like === 'DISLIKE');
  const rep = $('#ytm-repeat');
  rep.textContent = s.repeat === 'ONE' ? '🔂' : '🔁';
  rep.classList.toggle('on', s.repeat === 'ALL' || s.repeat === 'ONE');
  if (!ytm.volTimer) $('#ytm-vol').value = s.muted ? 0 : s.volume;
  $('#ytm-seek').max = Math.max(1, Math.round(s.duration || 0));
  $('#ytm-dur').textContent = fmtTime(s.duration);
  tickYtm();
  // marcar la canción actual en resultados y cola
  $$('.ytm-item[data-vid]').forEach((el) => el.classList.toggle('now', el.dataset.vid === s.videoId));
}
function tickYtm() {
  if (!ytm.state || ytm.seeking) return;
  const t = ytmNow();
  $('#ytm-seek').value = Math.round(t);
  $('#ytm-cur').textContent = fmtTime(t);
}
setInterval(() => { if (!document.hidden && $('#tab-music').classList.contains('active')) tickYtm(); }, 250);

$$('[data-ytm]').forEach((b) => b.addEventListener('click', async () => {
  const cmd = b.dataset.ytm;
  buzz(8);
  if (cmd === 'playpause' && ytm.state) { // respuesta inmediata en pantalla
    ytm.state.time = ytmNow(); ytm.stateAt = performance.now();
    ytm.state.playing = !ytm.state.playing; renderYtm();
  }
  const r = await ytmCmd(cmd);
  if (r.error) ytmError(r);
}));

const seek = $('#ytm-seek');
seek.addEventListener('input', () => { ytm.seeking = true; $('#ytm-cur').textContent = fmtTime(seek.value); });
seek.addEventListener('change', async () => {
  const time = Number(seek.value);
  if (ytm.state) { ytm.state.time = time; ytm.stateAt = performance.now(); }
  ytm.seeking = false;
  const r = await ytmCmd('seek', { time });
  if (r.error) ytmError(r);
});

function ytmSetVolume(v) {
  v = Math.max(0, Math.min(100, Math.round(v)));
  $('#ytm-vol').value = v;
  if (ytm.state) { ytm.state.volume = v; ytm.state.muted = false; }
  clearTimeout(ytm.volTimer);
  ytm.volTimer = setTimeout(() => { ytm.volTimer = null; ytmCmd('volume', { volume: v }); }, 80);
}
function ytmVolumeStep(d) { ytmSetVolume((ytm.state ? (ytm.state.muted ? 0 : ytm.state.volume) : 50) + d); }
$('#ytm-vol').addEventListener('input', (e) => ytmSetVolume(Number(e.target.value)));

$('#ytm-open').addEventListener('click', async () => {
  $('#ytm-note').textContent = 'Abriendo YouTube Music en el PC…';
  const r = await ytmCmd('open');
  $('#ytm-note').textContent = r.error ? '' : 'Listo. Si no empieza a sonar, busca una canción.';
  if (r.error) ytmError(r);
});

function itemHtml(it, extra = '') {
  return `<div class="ytm-item" ${extra}>
    <img src="${escHtml(it.thumb || 'icon.svg')}" alt="" loading="lazy" referrerpolicy="no-referrer">
    <div>${it.top ? '<div class="ytm-badge">Resultado principal</div>' : ''}<div class="t">${escHtml(it.title)}</div><div class="s">${escHtml(it.subtitle)}</div></div>
  </div>`;
}

$('#ytm-search-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const q = $('#ytm-q').value.trim();
  if (!q) return;
  $('#ytm-q').blur(); // oculta el teclado
  $('#ytm-note').textContent = 'Buscando…';
  $('#ytm-results').innerHTML = '';
  const r = await ytmCmd('search', { q });
  if (r.error) { ytmError(r); return; }
  const items = r.items || [];
  $('#ytm-note').textContent = items.length ? '' : 'Sin resultados.';
  $('#ytm-results').innerHTML = items.map((it) => itemHtml(it, `data-vid="${escHtml(it.videoId)}"`)).join('');
  renderYtm();
});
$('#ytm-results').addEventListener('click', async (e) => {
  const el = e.target.closest('.ytm-item');
  if (!el) return;
  buzz(12);
  $$('#ytm-results .ytm-item').forEach((x) => x.classList.toggle('now', x === el));
  $('#ytm-note').textContent = 'Reproduciendo en el PC…';
  const r = await ytmCmd('playVideo', { videoId: el.dataset.vid });
  if (r.error) ytmError(r);
  else $('#ytm-note').textContent = r.opened ? 'Se abrió YouTube Music en el PC con la canción.' : '';
});

async function loadQueue() {
  $('#ytm-queue').innerHTML = '<p class="note">Cargando…</p>';
  const r = await ytmCmd('queue');
  if (r.error) { $('#ytm-queue').innerHTML = ''; ytmError(r); return; }
  const items = r.items || [];
  $('#ytm-queue').innerHTML = items.length
    ? items.map((it) => itemHtml(it, `data-qi="${it.index}"${it.selected ? ' style="background:#1d2a3d"' : ''}`)).join('')
    : '<p class="note">La cola está vacía o no está visible. En el PC, abre la vista del reproductor de YouTube Music (toca la barra de abajo) y vuelve a actualizar.</p>';
}
$('#ytm-queue-box').addEventListener('toggle', (e) => { if (e.target.open) loadQueue(); });
$('#ytm-queue-refresh').addEventListener('click', loadQueue);
$('#ytm-queue').addEventListener('click', async (e) => {
  const el = e.target.closest('.ytm-item');
  if (!el) return;
  buzz(12);
  const r = await ytmCmd('queueJump', { index: Number(el.dataset.qi) });
  if (r.error) ytmError(r); else setTimeout(loadQueue, 700);
});
renderYtm();

/* ------------------------------------------------------------------ pestañas */
function showTab(name) {
  $$('.tabs button').forEach((b) => b.classList.toggle('active', b.dataset.tab === name));
  $$('.panel').forEach((p) => p.classList.toggle('active', p.id === 'tab-' + name));
  if (name !== 'keys') live.blur();
  store.set('rc_tab', name);
}
$$('.tabs button').forEach((b) => b.addEventListener('click', () => { showTab(b.dataset.tab); buzz(5); }));
showTab(store.get('rc_tab') || 'mouse');

/* ------------------------------------------------------------------ pantalla completa */
$('#fullscreen').addEventListener('click', () => {
  if (NATIVE) NATIVE.setFullscreen(!NATIVE.isFullscreen());
  else if (document.fullscreenElement) document.exitFullscreen?.();
  else document.documentElement.requestFullscreen?.({ navigationUI: 'hide' }).catch(() => {});
});

/* ------------------------------------------------------------------ pantalla de ajustes */
const CM_PX = 96 / 2.54; // píxeles CSS por centímetro
function renderSettings() {
  $('#s-sens').value = S.sens; $('#v-sens').textContent = S.sens.toFixed(1) + '×';
  $('#s-accel').value = S.accel; $('#v-accel').textContent = S.accel.toFixed(2);
  $('#s-scroll').value = S.scroll; $('#v-scroll').textContent = S.scroll.toFixed(1) + '×';
  for (const k of ['tap', 'longpress', 'natural', 'strip', 'haptic', 'awake']) $('#s-' + k).checked = S[k];
  $('#s-hwvol').value = S.hwvol;
  $('#s-smooth').value = String(S.smooth);
  $('#s-gyro').value = S.gyro; $('#v-gyro').textContent = S.gyro.toFixed(1) + '×';
  applyNative();
  const slow = Math.round(CM_PX * S.sens);
  const fast = Math.round(CM_PX * S.sens * (1 + S.accel * 2));
  $('#h-sens').textContent = `Mover el dedo 1 cm ≈ ${slow} px en el PC (lento) · ~${fast} px (rápido).`;
  $('#strip').classList.toggle('hidden', !S.strip);
}
for (const k of ['sens', 'accel', 'scroll', 'gyro']) {
  $('#s-' + k).addEventListener('input', (e) => { S[k] = parseFloat(e.target.value); saveSettings(); renderSettings(); });
}
$('#s-hwvol').addEventListener('change', (e) => { S.hwvol = e.target.value; saveSettings(); renderSettings(); });
$('#s-smooth').addEventListener('change', (e) => { S.smooth = parseInt(e.target.value, 10); saveSettings(); renderSettings(); sendConfig(); });
if (NATIVE) {
  $('#native-settings').hidden = false;
  if (!NATIVE.hasGyro()) $('#gyro-setting').hidden = true;
  $('#to-launcher').addEventListener('click', () => NATIVE.home());
}
for (const k of ['tap', 'longpress', 'natural', 'strip', 'haptic', 'awake']) {
  $('#s-' + k).addEventListener('change', (e) => { S[k] = e.target.checked; saveSettings(); renderSettings(); });
}
$('#reset').addEventListener('click', () => { S = { ...DEFAULTS }; saveSettings(); renderSettings(); buzz(15); });
$('#unpair').addEventListener('click', () => {
  if (!confirm('¿Olvidar este PC? Tendrás que ingresar el PIN otra vez.')) return;
  store.del('rc_token'); token = '';
  const sock = ws; ws = null;
  if (sock) { sock.onclose = null; sock.close(); }
  connect();
});
$('#info').textContent = `Servidor: ${location.host}. Solo funciona dentro de tu red Wi-Fi local.` +
  (NATIVE ? ` App Android v${NATIVE.version()}.` : '');
renderSettings();

connect();
