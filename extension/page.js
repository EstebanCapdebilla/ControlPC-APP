/*
 * Corre dentro de music.youtube.com (mundo de la página) para usar su reproductor,
 * su búsqueda y su cola. Habla con content.js mediante window.postMessage.
 * Nada sale de tu navegador salvo hacia el servidor local de tu PC.
 */
(() => {
  if (window.__rcpcPage) return;
  window.__rcpcPage = true;

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const player = () => document.getElementById('movie_player');
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  /* ----------------------------------------------------------- estado actual */
  function likeStatus() {
    const r = $('ytmusic-player-bar ytmusic-like-button-renderer');
    return (r && r.getAttribute('like-status')) || 'INDIFFERENT';
  }
  function repeatMode() {
    const b = $('ytmusic-player-bar');
    const m = b && (b.getAttribute('repeat-mode') || b.repeatMode_ || b.repeatMode);
    return typeof m === 'string' ? m : 'NONE';
  }
  function state() {
    const p = player();
    if (!p || typeof p.getVideoData !== 'function') return { ready: false };
    const vd = p.getVideoData() || {};
    const md = navigator.mediaSession && navigator.mediaSession.metadata;
    const art = md && md.artwork && md.artwork.length ? md.artwork[md.artwork.length - 1].src : '';
    return {
      ready: !!vd.video_id,
      videoId: vd.video_id || '',
      title: (md && md.title) || vd.title || '',
      artist: (md && md.artist) || vd.author || '',
      album: (md && md.album) || '',
      art,
      duration: Number(p.getDuration && p.getDuration()) || 0,
      time: Number(p.getCurrentTime && p.getCurrentTime()) || 0,
      playing: p.getPlayerState && p.getPlayerState() === 1,
      volume: p.getVolume ? p.getVolume() : 100,
      muted: p.isMuted ? p.isMuted() : false,
      like: likeStatus(),
      repeat: repeatMode(),
      ad: p.classList.contains('ad-showing'), // anuncio (cuentas sin Premium)
    };
  }

  let lastSig = '', lastPush = 0;
  function push(force) {
    const s = state();
    const sig = [s.videoId, s.playing, s.like, s.volume, s.muted, s.repeat, s.title, s.art, s.ad, Math.round(s.duration)].join('|');
    const now = Date.now();
    if (!force && sig === lastSig && now - lastPush < 5000) return;
    lastSig = sig; lastPush = now;
    window.postMessage({ __rcpc: 'page', kind: 'state', state: s }, location.origin);
  }
  setInterval(() => push(false), 700);
  for (const ev of ['play', 'pause', 'seeked', 'volumechange', 'loadedmetadata']) {
    document.addEventListener(ev, () => setTimeout(() => push(true), 60), true);
  }

  /* ----------------------------------------------------------- utilidades */
  function click(sel) {
    const el = $(sel);
    if (el) { el.click(); return true; }
    return false;
  }
  const texts = (runs) => (runs || []).map((r) => r.text).join('');
  function walk(o, fn) {
    if (!o || typeof o !== 'object') return;
    if (Array.isArray(o)) { for (const x of o) walk(x, fn); return; }
    fn(o);
    for (const k in o) walk(o[k], fn);
  }
  function lastThumb(t) {
    const arr = (t && t.musicThumbnailRenderer && t.musicThumbnailRenderer.thumbnail && t.musicThumbnailRenderer.thumbnail.thumbnails)
      || (t && t.thumbnails) || [];
    return arr.length ? arr[arr.length - 1].url : '';
  }
  function findWatch(o) {
    let v = '';
    walk(o, (x) => { if (!v && x.watchEndpoint && x.watchEndpoint.videoId) v = x.watchEndpoint.videoId; });
    return v;
  }

  /* ----------------------------------------------------------- búsqueda */
  async function authHeader() {
    // El mismo encabezado que usa la página para pedir resultados con tu sesión.
    const m = document.cookie.match(/(?:^|;\s*)(?:SAPISID|__Secure-3PAPISID)=([^;]+)/);
    if (!m || !crypto.subtle) return '';
    const ts = Math.floor(Date.now() / 1000);
    const buf = await crypto.subtle.digest('SHA-1', new TextEncoder().encode(`${ts} ${m[1]} ${location.origin}`));
    const hex = [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, '0')).join('');
    return `SAPISIDHASH ${ts}_${hex}`;
  }

  async function search(q) {
    const cfg = window.ytcfg;
    if (!cfg || !cfg.get) throw new Error('YouTube Music aún no termina de cargar');
    const key = cfg.get('INNERTUBE_API_KEY');
    const headers = {
      'Content-Type': 'application/json',
      'X-Goog-AuthUser': String(cfg.get('SESSION_INDEX') || 0),
      'X-Origin': location.origin,
      'X-Youtube-Client-Name': String(cfg.get('INNERTUBE_CONTEXT_CLIENT_NAME') || 67),
      'X-Youtube-Client-Version': String(cfg.get('INNERTUBE_CLIENT_VERSION') || ''),
    };
    const auth = await authHeader();
    if (auth) headers.Authorization = auth;
    const r = await fetch(`/youtubei/v1/search?prettyPrint=false${key ? '&key=' + encodeURIComponent(key) : ''}`, {
      method: 'POST', credentials: 'include', headers,
      body: JSON.stringify({ context: cfg.get('INNERTUBE_CONTEXT'), query: q }),
    });
    if (!r.ok) throw new Error('La búsqueda falló (HTTP ' + r.status + ')');
    return parseResults(await r.json());
  }

  function parseResults(j) {
    const items = [], seen = new Set();
    walk(j, (o) => {
      const card = o.musicCardShelfRenderer; // "Resultado principal"
      if (card) {
        const vid = findWatch(card.title) || findWatch(card.thumbnailOverlay);
        if (vid && !seen.has(vid)) {
          seen.add(vid);
          items.push({ videoId: vid, title: texts(card.title && card.title.runs), subtitle: texts(card.subtitle && card.subtitle.runs), thumb: lastThumb(card.thumbnail), top: true });
        }
      }
      const it = o.musicResponsiveListItemRenderer;
      if (it) {
        const vid = (it.playlistItemData && it.playlistItemData.videoId) || findWatch(it.overlay);
        if (!vid || seen.has(vid)) return;
        seen.add(vid);
        const cols = it.flexColumns || [];
        const col = (i) => texts(cols[i] && cols[i].musicResponsiveListItemFlexColumnRenderer && cols[i].musicResponsiveListItemFlexColumnRenderer.text && cols[i].musicResponsiveListItemFlexColumnRenderer.text.runs);
        items.push({ videoId: vid, title: col(0), subtitle: [col(1), col(2)].filter(Boolean).join(' • '), thumb: lastThumb(it.thumbnail) });
      }
    });
    return items.slice(0, 30);
  }

  /* ----------------------------------------------------------- reproducir una canción */
  async function playVideo(videoId) {
    const p = player();
    const current = () => { try { return (player().getVideoData() || {}).video_id; } catch { return ''; } };
    const endpoint = { watchEndpoint: { videoId } };
    const app = $('ytmusic-app');
    // 1) Navegación interna de YouTube Music (arma la "radio" de esa canción como en la app)
    try {
      if (app && typeof app.navigate_ === 'function') app.navigate_(endpoint);
      else if (app) app.dispatchEvent(new CustomEvent('yt-navigate', { bubbles: true, composed: true, detail: { endpoint } }));
    } catch { /* sigue con el plan B */ }
    for (let i = 0; i < 25; i++) { await sleep(100); if (current() === videoId) return { ok: true, via: 'navigate' }; }
    // 2) Cargar directamente en el reproductor
    if (p && typeof p.loadVideoById === 'function') {
      p.loadVideoById(videoId);
      for (let i = 0; i < 25; i++) { await sleep(100); if (current() === videoId) return { ok: true, via: 'player' }; }
    }
    // 3) Último recurso: abrir la canción (recarga la página)
    location.href = '/watch?v=' + encodeURIComponent(videoId);
    return { ok: true, via: 'reload' };
  }

  /* ----------------------------------------------------------- cola */
  function queueEls() {
    return $$('ytmusic-player-queue ytmusic-player-queue-item').filter((el) => !el.closest('#counterpart-renderer'));
  }
  function queue() {
    return {
      items: queueEls().slice(0, 100).map((el, index) => {
        // Los datos de la canción están en el propio elemento (las imágenes cargan tarde)
        const d = el.data || {};
        const t = $('.song-title', el), b = $('.byline', el), img = $('img', el);
        const imgSrc = img && img.src && !img.src.startsWith('data:') ? img.src : '';
        const length = d.lengthText && d.lengthText.runs ? texts(d.lengthText.runs) : '';
        const by = (b && (b.getAttribute('title') || b.textContent) || texts(d.shortBylineText && d.shortBylineText.runs) || '').trim();
        return {
          index,
          videoId: d.videoId || '',
          title: (t && (t.getAttribute('title') || t.textContent) || texts(d.title && d.title.runs) || '').trim(),
          subtitle: [by, length].filter(Boolean).join(' • '),
          thumb: lastThumb(d.thumbnail) || imgSrc,
          selected: el.hasAttribute('selected'),
        };
      }),
    };
  }
  function queueJump(index) {
    const el = queueEls()[index];
    if (!el) return { error: 'No está en la cola' };
    const btn = $('ytmusic-play-button-renderer', el) || $('.song-info', el) || el;
    btn.click();
    return { ok: true };
  }

  /* ----------------------------------------------------------- comandos */
  async function run(cmd, a) {
    const p = player();
    switch (cmd) {
      case 'state': return { state: state() };
      case 'playpause':
        if (!click('ytmusic-player-bar #play-pause-button') && p) (p.getPlayerState() === 1 ? p.pauseVideo() : p.playVideo());
        return { ok: true };
      case 'next':
        if (!click('ytmusic-player-bar .next-button') && p) p.nextVideo();
        return { ok: true };
      case 'prev':
        if (!click('ytmusic-player-bar .previous-button') && p) p.previousVideo();
        return { ok: true };
      case 'seek':
        if (p) p.seekTo(Math.max(0, Number(a.time) || 0), true);
        return { ok: true };
      case 'volume': {
        const v = Math.max(0, Math.min(100, Math.round(Number(a.volume))));
        if (p) { p.setVolume(v); if (v > 0 && p.isMuted()) p.unMute(); }
        const slider = $('ytmusic-player-bar #volume-slider');
        if (slider) { try { slider.value = v; } catch { /* */ } }
        return { ok: true };
      }
      case 'like':
        return { ok: click('ytmusic-player-bar ytmusic-like-button-renderer #button-shape-like button')
          || click('ytmusic-player-bar ytmusic-like-button-renderer .like') };
      case 'dislike':
        return { ok: click('ytmusic-player-bar ytmusic-like-button-renderer #button-shape-dislike button')
          || click('ytmusic-player-bar ytmusic-like-button-renderer .dislike') };
      case 'shuffle': return { ok: click('ytmusic-player-bar .shuffle') };
      case 'repeat': return { ok: click('ytmusic-player-bar .repeat') };
      case 'search': return { items: await search(String(a.q || '').slice(0, 200)) };
      case 'playVideo': return playVideo(String(a.videoId || ''));
      case 'queue': return queue();
      case 'queueJump': return queueJump(Number(a.index));
      default: return { error: 'comando desconocido: ' + cmd };
    }
  }

  window.addEventListener('message', async (e) => {
    if (e.source !== window || !e.data || e.data.__rcpc !== 'ext') return;
    const { id, cmd, args } = e.data;
    let result;
    try { result = await run(cmd, args || {}); } catch (err) { result = { error: String((err && err.message) || err) }; }
    window.postMessage({ __rcpc: 'page', kind: 'res', id, result }, location.origin);
    setTimeout(() => push(true), 200);
  });

  push(true);
})();
