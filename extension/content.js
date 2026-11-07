/*
 * Puente entre la extensión y la página (page.js corre dentro de la página para
 * poder usar el reproductor y la búsqueda de YouTube Music).
 */
(() => {
  // Al actualizar la extensión, esta copia reemplaza a la anterior (ver page.js).
  const VERSION = 4;
  const prev = window.__rcpcContent2;
  if (prev && prev.version >= VERSION) return;
  if (prev && prev.stop) { try { prev.stop(); } catch { /* */ } }

  const pending = new Map();
  let seq = 0;

  const onPage = (e) => {
    if (e.source !== window || !e.data || e.data.__rcpc2 !== 'page') return;
    const d = e.data;
    if (d.kind === 'state') {
      try { chrome.runtime.sendMessage({ rcpcState: d.state }); } catch { /* extensión recargada */ }
    } else if (d.kind === 'res' && pending.has(d.id)) {
      pending.get(d.id)(d.result);
      pending.delete(d.id);
    }
  };

  const onExt = (msg, _sender, sendResponse) => {
    if (!msg || !msg.rcpc) return false;
    const id = ++seq;
    const timer = setTimeout(() => {
      if (pending.has(id)) { pending.delete(id); sendResponse({ error: 'tiempo agotado' }); }
    }, 10000);
    pending.set(id, (result) => { clearTimeout(timer); sendResponse(result); });
    window.postMessage({ __rcpc2: 'ext', id, cmd: msg.cmd, args: msg.args }, location.origin);
    return true; // respuesta asíncrona
  };

  window.addEventListener('message', onPage);
  chrome.runtime.onMessage.addListener(onExt);
  window.__rcpcContent2 = {
    version: VERSION,
    stop: () => {
      window.removeEventListener('message', onPage);
      try { chrome.runtime.onMessage.removeListener(onExt); } catch { /* */ }
    },
  };
})();
