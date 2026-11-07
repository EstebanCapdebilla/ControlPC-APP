/*
 * Corre dentro de music.youtube.com (mundo de la página) para usar su reproductor,
 * su búsqueda y su cola. Habla con content.js mediante window.postMessage.
 * Nada sale de tu navegador salvo hacia el servidor local de tu PC.
 */
(() => {
  /* Al actualizar la extensión se vuelve a inyectar este archivo en la pestaña abierta:
     la versión nueva apaga a la anterior en vez de retirarse. Los mensajes usan la
     marca __rcpc2 para que scripts de la versión 1.0 (sin forma de apagarlos) no respondan. */
  const VERSION = 4;
  const prev = window.__rcpcPage2;
  if (prev && prev.version >= VERSION) return;
  if (prev && prev.stop) { try { prev.stop(); } catch { /* */ } }
  const cleanup = [];
  window.__rcpcPage2 = { version: VERSION, stop: () => cleanup.forEach((f) => f()) };
  const listen = (target, ev, fn, opt) => { target.addEventListener(ev, fn, opt); cleanup.push(() => target.removeEventListener(ev, fn, opt)); };

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
    window.postMessage({ __rcpc2: 'page', kind: 'state', state: s }, location.origin);
  }
  const tick = setInterval(() => push(false), 700);
  cleanup.push(() => clearInterval(tick));
  for (const ev of ['play', 'pause', 'seeked', 'volumechange', 'loadedmetadata']) {
    listen(document, ev, () => setTimeout(() => push(true), 60), true);
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

  /* Pide datos a YouTube Music igual que la propia página (con tu sesión). */
  async function innertube(endpoint, body, what, query = '') {
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
    const r = await fetch(`/youtubei/v1/${endpoint}?prettyPrint=false${query}${key ? '&key=' + encodeURIComponent(key) : ''}`, {
      method: 'POST', credentials: 'include', headers,
      body: JSON.stringify({ context: cfg.get('INNERTUBE_CONTEXT'), ...body }),
    });
    if (!r.ok) throw new Error(`${what} falló (HTTP ${r.status})`);
    return r.json();
  }

  async function search(q) {
    return parseResults(await innertube('search', { query: q }, 'La búsqueda'));
  }

  /* ----------------------------------------------------------- listas de reproducción */
  const isPlaylistBrowse = (be) => be && typeof be.browseId === 'string' && /^VL/.test(be.browseId);
  function playEndpointOf(o) {
    // El botón ▶ de la tarjeta trae el endpoint exacto que usa YouTube Music para reproducir la lista
    let ep = null;
    walk(o, (x) => {
      const pb = x.musicPlayButtonRenderer;
      if (!ep && pb && pb.playNavigationEndpoint) ep = pb.playNavigationEndpoint;
    });
    return ep && (ep.watchPlaylistEndpoint || ep.watchEndpoint) ? ep : null;
  }

  async function playlists() {
    const j = await innertube('browse', { browseId: 'FEmusic_liked_playlists' }, 'Cargar tus listas');
    const items = [], seen = new Set();
    walk(j, (o) => {
      const r = o.musicTwoRowItemRenderer || o.musicResponsiveListItemRenderer;
      if (!r) return;
      const be = r.navigationEndpoint && r.navigationEndpoint.browseEndpoint;
      if (!isPlaylistBrowse(be)) return;
      const id = be.browseId.slice(2);
      if (seen.has(id)) return;
      seen.add(id);
      let title, subtitle;
      if (o.musicTwoRowItemRenderer) {
        title = texts(r.title && r.title.runs);
        subtitle = texts(r.subtitle && r.subtitle.runs);
      } else {
        const cols = r.flexColumns || [];
        const col = (i) => texts(cols[i] && cols[i].musicResponsiveListItemFlexColumnRenderer && cols[i].musicResponsiveListItemFlexColumnRenderer.text && cols[i].musicResponsiveListItemFlexColumnRenderer.text.runs);
        title = col(0); subtitle = [col(1), col(2)].filter(Boolean).join(' • ');
      }
      const ep = playEndpointOf(r.thumbnailOverlay || r.overlay);
      if (ep) playEndpoints.set(id, ep);
      items.push({ playlistId: id, title, subtitle, thumb: lastThumb(r.thumbnailRenderer || r.thumbnail) });
    });
    return { items: items.slice(0, 200) };
  }
  // Se guardan aquí (no se mandan al celular): el celular solo pide "reproducir la lista X".
  const playEndpoints = new Map();

  /* Una lista llega por partes (~100 canciones). Sin `token` se pide la primera parte;
     la respuesta trae `next` para pedir la siguiente (vacío = no hay más). */
  async function playlistSongs(playlistId, token) {
    let j, scope;
    if (!token) {
      j = await innertube('browse', { browseId: 'VL' + playlistId }, 'Cargar la lista');
      // Solo la tabla de canciones de la lista (no las sugerencias ni otras secciones)
      walk(j, (o) => { if (!scope && o.musicPlaylistShelfRenderer) scope = o.musicPlaylistShelfRenderer; });
      scope = scope || j;
    } else {
      try {
        j = await innertube('browse', { continuation: token }, 'Cargar más canciones');
      } catch {
        j = null;
      }
      if (!j || !parseResults(j, 1).length) { // formato anterior de YouTube Music
        const t = encodeURIComponent(token);
        j = await innertube('browse', {}, 'Cargar más canciones', `&ctoken=${t}&continuation=${t}&type=next`);
      }
      scope = j;
    }
    return { items: parseResults(scope, 1000), next: nextToken(scope) };
  }

  function nextToken(o) {
    let t = '';
    walk(o, (x) => {
      if (t) return;
      const c = x.continuationItemRenderer;
      const cmd = c && c.continuationEndpoint && c.continuationEndpoint.continuationCommand;
      if (cmd && cmd.token) t = cmd.token;
      else if (x.nextContinuationData && x.nextContinuationData.continuation) t = x.nextContinuationData.continuation;
    });
    return t;
  }

  /* Navegación interna de YouTube Music (como al tocar en la página: arma la cola). */
  function navigate(endpoint) {
    const app = $('ytmusic-app');
    if (!app) return false;
    try {
      if (typeof app.navigate_ === 'function') app.navigate_(endpoint);
      else app.dispatchEvent(new CustomEvent('yt-navigate', { bubbles: true, composed: true, detail: { endpoint } }));
      return true;
    } catch { return false; }
  }

  async function playPlaylist(playlistId) {
    if (!playlistId) return { error: 'Falta la lista' };
    const before = (() => { try { return (player().getVideoData() || {}).video_id; } catch { return ''; } })();
    const endpoint = playEndpoints.get(playlistId) || { watchPlaylistEndpoint: { playlistId } };
    if (navigate(endpoint)) {
      for (let i = 0; i < 30; i++) {
        await sleep(100);
        try { const v = (player().getVideoData() || {}).video_id; if (v && v !== before) return { ok: true }; } catch { /* */ }
      }
    }
    // Último recurso: abrir la lista directamente (recarga la página)
    location.href = '/watch?list=' + encodeURIComponent(playlistId);
    return { ok: true, via: 'reload' };
  }

  function parseResults(j, max = 30) {
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
    return items.slice(0, max);
  }

  /* ----------------------------------------------------------- reproducir una canción */
  /* playlistId opcional: la canción suena dentro de esa lista (sigue con las demás). */
  async function playVideo(videoId, playlistId) {
    const p = player();
    const current = () => { try { return (player().getVideoData() || {}).video_id; } catch { return ''; } };
    const endpoint = { watchEndpoint: playlistId ? { videoId, playlistId } : { videoId } };
    // 1) Navegación interna de YouTube Music (arma la "radio" de esa canción, o la lista, como en la app)
    if (navigate(endpoint)) {
      for (let i = 0; i < 25; i++) { await sleep(100); if (current() === videoId) return { ok: true, via: 'navigate' }; }
    }
    // 2) Cargar directamente en el reproductor
    if (p && typeof p.loadVideoById === 'function') {
      p.loadVideoById(videoId);
      for (let i = 0; i < 25; i++) { await sleep(100); if (current() === videoId) return { ok: true, via: 'player' }; }
    }
    // 3) Último recurso: abrir la canción (recarga la página)
    location.href = '/watch?v=' + encodeURIComponent(videoId) + (playlistId ? '&list=' + encodeURIComponent(playlistId) : '');
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
      case 'playVideo': return playVideo(String(a.videoId || ''), a.playlistId ? String(a.playlistId) : '');
      case 'playlists': return playlists();
      case 'playlistSongs': return playlistSongs(String(a.playlistId || ''), a.next ? String(a.next) : '');
      case 'playPlaylist': return playPlaylist(String(a.playlistId || ''));
      case 'queue': return queue();
      case 'queueJump': return queueJump(Number(a.index));
      default: return { error: 'comando desconocido: ' + cmd };
    }
  }

  listen(window, 'message', async (e) => {
    if (e.source !== window || !e.data || e.data.__rcpc2 !== 'ext') return;
    const { id, cmd, args } = e.data;
    let result;
    try { result = await run(cmd, args || {}); } catch (err) { result = { error: String((err && err.message) || err) }; }
    window.postMessage({ __rcpc2: 'page', kind: 'res', id, result }, location.origin);
    setTimeout(() => push(true), 200);
  });

  push(true);
})();
