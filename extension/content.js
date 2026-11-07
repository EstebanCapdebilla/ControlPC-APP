/*
 * Puente entre la extensión y la página (page.js corre dentro de la página para
 * poder usar el reproductor y la búsqueda de YouTube Music).
 */
(() => {
  if (window.__rcpcContent) return;
  window.__rcpcContent = true;

  const pending = new Map();
  let seq = 0;

  window.addEventListener('message', (e) => {
    if (e.source !== window || !e.data || e.data.__rcpc !== 'page') return;
    const d = e.data;
    if (d.kind === 'state') {
      try { chrome.runtime.sendMessage({ rcpcState: d.state }); } catch { /* extensión recargada */ }
    } else if (d.kind === 'res' && pending.has(d.id)) {
      pending.get(d.id)(d.result);
      pending.delete(d.id);
    }
  });

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (!msg || !msg.rcpc) return false;
    const id = ++seq;
    const timer = setTimeout(() => {
      if (pending.has(id)) { pending.delete(id); sendResponse({ error: 'tiempo agotado' }); }
    }, 8000);
    pending.set(id, (result) => { clearTimeout(timer); sendResponse(result); });
    window.postMessage({ __rcpc: 'ext', id, cmd: msg.cmd, args: msg.args }, location.origin);
    return true; // respuesta asíncrona
  });
})();
