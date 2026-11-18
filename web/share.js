'use strict';
/*
 * Corre en una ventana escondida del navegador del PC (la abre server.py).
 * Captura la pantalla y la envía como video (WebRTC) a cada celular que la está viendo.
 * El servidor solo reenvía los mensajes para ponerlos en contacto (señalización).
 */
const key = new URLSearchParams(location.search).get('k') || '';
const st = (t) => { document.getElementById('st').textContent = t; };
let ws = null;
let stream = null;
const peers = new Map(); // id del celular -> RTCPeerConnection
const waiting = new Set(); // celulares que pidieron video antes de que la captura estuviera lista

const send = (m) => { if (ws && ws.readyState === 1) ws.send(JSON.stringify(m)); };

async function capture() {
  try {
    stream = await navigator.mediaDevices.getDisplayMedia({
      video: { frameRate: { ideal: 60, max: 60 }, width: { max: 1920 }, height: { max: 1200 }, cursor: 'always' },
      audio: false,
    });
  } catch (e) {
    st('No se pudo capturar la pantalla: ' + e.name);
    send(['error', `${e.name}: ${e.message}`]);
    return;
  }
  const track = stream.getVideoTracks()[0];
  track.contentHint = 'detail'; // texto nítido (escritorio), no solo movimiento
  track.onended = () => { st('Captura detenida'); send(['ended']); };
  const s = track.getSettings();
  st(`Compartiendo ${s.width}×${s.height}`);
  send(['ready', { width: s.width, height: s.height, fps: s.frameRate, label: track.label }]);
  for (const id of waiting) offer(id);
  waiting.clear();
}

function close(id) {
  const pc = peers.get(id);
  if (pc) { pc.close(); peers.delete(id); }
}

async function offer(id) {
  if (!stream) { waiting.add(id); return; }
  close(id);
  const pc = new RTCPeerConnection({ iceServers: [] }); // solo red local
  peers.set(id, pc);
  const track = stream.getVideoTracks()[0];
  const tr = pc.addTransceiver(track, { direction: 'sendonly', streams: [stream] });
  // H.264 primero: los celulares lo decodifican por hardware (menos batería y retraso)
  try {
    const caps = RTCRtpSender.getCapabilities('video').codecs;
    const rank = (c) => (/h264/i.test(c.mimeType) ? 0 : /vp8/i.test(c.mimeType) ? 1 : 2);
    tr.setCodecPreferences([...caps].sort((a, b) => rank(a) - rank(b)));
  } catch { /* el navegador elige */ }
  pc.onicecandidate = (e) => { if (e.candidate) send(['sig', id, { candidate: e.candidate.toJSON() }]); };
  pc.onconnectionstatechange = () => {
    if (pc.connectionState === 'connected') {
      st(`Enviando video a ${peers.size} celular(es)`);
      tune(tr.sender);
    }
    if (pc.connectionState === 'failed') close(id);
  };
  await pc.setLocalDescription(await pc.createOffer());
  send(['sig', id, { sdp: pc.localDescription.toJSON() }]);
}

async function tune(sender) {
  try {
    const p = sender.getParameters();
    if (!p.encodings || !p.encodings.length) p.encodings = [{}];
    p.encodings[0].maxBitrate = 8_000_000; // red local: suficiente para 1080p nítido
    p.encodings[0].maxFramerate = 60;
    p.degradationPreference = 'maintain-resolution';
    await sender.setParameters(p);
  } catch { /* valores por defecto */ }
}

async function signal(id, data) {
  const pc = peers.get(id);
  if (!pc) return;
  try {
    if (data.sdp) await pc.setRemoteDescription(data.sdp);
    else if (data.candidate) await pc.addIceCandidate(data.candidate);
  } catch (e) { console.warn('señal', e); }
}

function connect() {
  ws = new WebSocket(`ws://${location.host}/share?k=${encodeURIComponent(key)}`);
  ws.onopen = () => { if (!stream) capture(); else send(['ready', {}]); };
  ws.onmessage = (e) => {
    let m; try { m = JSON.parse(e.data); } catch { return; }
    if (m[0] === 'viewer') offer(m[1]);
    else if (m[0] === 'sig') signal(m[1], m[2] || {});
    else if (m[0] === 'bye') { close(m[1]); waiting.delete(m[1]); }
  };
  ws.onclose = () => { st('Desconectado del servidor'); setTimeout(connect, 1500); };
}
connect();
