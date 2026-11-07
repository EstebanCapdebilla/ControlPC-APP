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
const DEFAULTS = { sens: 1.6, accel: 0.6, scroll: 1.5, natural: true, tap: true, longpress: true, strip: true, haptic: true };
let S = { ...DEFAULTS };
try { Object.assign(S, JSON.parse(store.get('rc_settings') || '{}')); } catch { /* */ }
const saveSettings = () => store.set('rc_settings', JSON.stringify(S));

const buzz = (p = 8) => { if (S.haptic && navigator.vibrate) try { navigator.vibrate(p); } catch { /* */ } };

/* ------------------------------------------------------------------ conexión */
let ws = null, retry = 0, retryTimer = null;

function setStatus(state, text) {
  const dot = $('#dot');
  dot.className = 'dot' + (state === 'ok' ? ' ok' : state === 'bad' ? ' bad' : '');
  $('#status').textContent = text;
}

function showOverlay(title, text) {
  $('#ov-title').textContent = title;
  $('#ov-text').textContent = text;
  $('#overlay').classList.remove('hidden');
}
const hideOverlay = () => $('#overlay').classList.add('hidden');

function connect() {
  clearTimeout(retryTimer);
  if (ws && ws.readyState <= 1) return;
  if (!token) {
    setStatus('bad', 'Sin vincular');
    showOverlay('Falta vincular', 'Abre esta página escaneando el código QR que muestra el PC (python server.py).');
    return;
  }
  setStatus('wait', 'Conectando…');
  const sock = new WebSocket(`ws://${location.host}/ws?t=${encodeURIComponent(token)}`);
  ws = sock;
  sock.onopen = () => {
    retry = 0;
    setStatus('ok', 'Conectado');
    hideOverlay();
    ping();
  };
  sock.onmessage = (e) => {
    let m; try { m = JSON.parse(e.data); } catch { return; }
    if (m[0] === 'p') $('#latency').textContent = Math.round(performance.now() - m[1]) + ' ms';
    else if (m[0] === 'hello') $('#pcname').textContent = '· ' + m[1];
  };
  sock.onclose = (e) => {
    if (ws === sock) ws = null;
    $('#latency').textContent = '';
    if (e.code === 4001) {
      setStatus('bad', 'Código inválido');
      showOverlay('Código inválido', 'El PC generó un código nuevo. Escanea otra vez el QR que aparece en el PC.');
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
      mode: inStrip ? 'strip' : 'move', drag: false, long: false, pts: new Map(), longTimer: null,
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
    const speed = d / dt; // px por ms
    const gain = S.sens * (1 + S.accel * Math.min(speed, 4));
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
  if (document.fullscreenElement) document.exitFullscreen?.();
  else document.documentElement.requestFullscreen?.({ navigationUI: 'hide' }).catch(() => {});
});

/* ------------------------------------------------------------------ pantalla de ajustes */
const CM_PX = 96 / 2.54; // píxeles CSS por centímetro
function renderSettings() {
  $('#s-sens').value = S.sens; $('#v-sens').textContent = S.sens.toFixed(1) + '×';
  $('#s-accel').value = S.accel; $('#v-accel').textContent = S.accel.toFixed(2);
  $('#s-scroll').value = S.scroll; $('#v-scroll').textContent = S.scroll.toFixed(1) + '×';
  for (const k of ['tap', 'longpress', 'natural', 'strip', 'haptic']) $('#s-' + k).checked = S[k];
  const slow = Math.round(CM_PX * S.sens);
  const fast = Math.round(CM_PX * S.sens * (1 + S.accel * 2));
  $('#h-sens').textContent = `Mover el dedo 1 cm ≈ ${slow} px en el PC (lento) · ~${fast} px (rápido).`;
  $('#strip').classList.toggle('hidden', !S.strip);
}
for (const k of ['sens', 'accel', 'scroll']) {
  $('#s-' + k).addEventListener('input', (e) => { S[k] = parseFloat(e.target.value); saveSettings(); renderSettings(); });
}
for (const k of ['tap', 'longpress', 'natural', 'strip', 'haptic']) {
  $('#s-' + k).addEventListener('change', (e) => { S[k] = e.target.checked; saveSettings(); renderSettings(); });
}
$('#reset').addEventListener('click', () => { S = { ...DEFAULTS }; saveSettings(); renderSettings(); buzz(15); });
$('#unpair').addEventListener('click', () => {
  if (!confirm('¿Olvidar este PC? Tendrás que escanear el QR otra vez.')) return;
  store.del('rc_token'); token = '';
  if (ws) ws.close();
  connect();
});
$('#info').textContent = `Servidor: ${location.host}. Solo funciona dentro de tu red Wi-Fi local.`;
renderSettings();

connect();
