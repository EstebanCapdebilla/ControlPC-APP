/*
 * Control PC - YouTube Music (service worker)
 * Se conecta al servidor local del PC (server.py) y hace de puente entre el
 * celular y la pestaña de music.youtube.com.
 */
const SERVER = 'ws://127.0.0.1:8765/ext';
const YTM = 'https://music.youtube.com/';
let ws = null;
let retryTimer = null;

function connect() {
  if (ws && ws.readyState <= 1) return;
  clearTimeout(retryTimer);
  try { ws = new WebSocket(SERVER); } catch (e) { scheduleRetry(); return; }
  ws.onopen = () => { sendState(); };
  ws.onmessage = (e) => {
    let m; try { m = JSON.parse(e.data); } catch { return; }
    if (m[0] === 'cmd') handleCommand(m[1]);
  };
  ws.onclose = () => { ws = null; scheduleRetry(); };
  ws.onerror = () => { /* onclose se encarga */ };
}
function scheduleRetry() { clearTimeout(retryTimer); retryTimer = setTimeout(connect, 3000); }
function out(msg) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(msg)); }

// Mantener vivo el service worker y la conexión (Chrome lo duerme si está inactivo).
setInterval(() => out(['ka']), 20000);
chrome.alarms.create('rcpc-keepalive', { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener(() => connect());
chrome.runtime.onStartup.addListener(connect);

// Al instalar: inyectar los scripts en las pestañas de YouTube Music ya abiertas.
chrome.runtime.onInstalled.addListener(async () => {
  const tabs = await chrome.tabs.query({ url: YTM + '*' });
  for (const t of tabs) {
    try {
      await chrome.scripting.executeScript({ target: { tabId: t.id }, files: ['page.js'], world: 'MAIN' });
      await chrome.scripting.executeScript({ target: { tabId: t.id }, files: ['content.js'] });
    } catch (e) { /* pestaña no disponible */ }
  }
  connect();
});

async function findTab() {
  const tabs = await chrome.tabs.query({ url: YTM + '*' });
  if (!tabs.length) return null;
  // Preferir la pestaña que está sonando
  return tabs.find((t) => t.audible) || tabs.find((t) => t.active) || tabs[0];
}

async function handleCommand(c) {
  const { id, cmd, args = {} } = c || {};
  const reply = (res) => out(['res', { id, ...res }]);
  try {
    let tab = await findTab();
    if (cmd === 'open') {
      if (tab) await chrome.tabs.update(tab.id, { active: true });
      else tab = await chrome.tabs.create({ url: YTM, active: true });
      return reply({ ok: true });
    }
    if (!tab) {
      if (cmd === 'playVideo' && args.videoId) {
        await chrome.tabs.create({ url: `${YTM}watch?v=${encodeURIComponent(args.videoId)}`, active: true });
        return reply({ ok: true, opened: true });
      }
      return reply({ error: 'notab' });
    }
    const res = await chrome.tabs.sendMessage(tab.id, { rcpc: true, cmd, args });
    reply(res || { error: 'sin respuesta' });
  } catch (e) {
    reply({ error: String(e && e.message || e) });
  }
}

// Estado (canción actual, progreso...) que manda la pestaña
let lastState = null;
chrome.runtime.onMessage.addListener((msg, sender) => {
  if (msg && msg.rcpcState) {
    lastState = { ...msg.rcpcState, tabId: sender.tab && sender.tab.id };
    out(['state', lastState]);
  }
});
function sendState() { if (lastState) out(['state', lastState]); }

// Si se cierra la pestaña de YouTube Music, avisar al celular
chrome.tabs.onRemoved.addListener(async () => {
  if (!(await findTab())) { lastState = null; out(['state', null]); }
});

connect();
