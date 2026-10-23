/* Contact sheets give immediate visual feedback without a second A/V player. */
window.createSeekPreview = function (id, node) {
  const image = node.querySelector('.seek-frame'), caption = node.querySelector('small');
  const loaded = new Map();
  let manifest = null, stopped = false, at = 0, active = false, retry = null;
  const update = () => {
    if (stopped || !active || !manifest) return;
    const frame = Math.min(manifest.frames - 1, Math.max(0, Math.floor(at / manifest.interval)));
    const perSheet = manifest.columns * manifest.rows, sheet = Math.floor(frame / perSheet);
    const url = manifest.sheets[sheet], cell = frame % perSheet;
    if (!loaded.has(url)) {
      const entry = new Image(); loaded.set(url, entry);
      entry.onload = update;
      entry.onerror = () => { loaded.delete(url); };
      entry.src = url;
    }
    const ready = loaded.get(url);
    const visible = !!ready?.complete && ready.naturalWidth > 0;
    image.hidden = !visible;
    if (visible) {
      image.style.backgroundImage = `url("${url}")`;
      image.style.backgroundSize = `${manifest.columns * 100}% ${manifest.rows * 100}%`;
      image.style.backgroundPosition = `${cell % manifest.columns / (manifest.columns - 1) * 100}% ${Math.floor(cell / manifest.columns) / (manifest.rows - 1) * 100}%`;
      image.dataset.frame = String(frame);
      caption.textContent = '画面预览 · 松手定位原画';
    }
  };
  const load = async () => {
    try {
      const data = await api(`/media/${id}/preview`);
      if (stopped) return;
      if (data.status === 'ready') {
        manifest = data;
        const first = new Image(); loaded.set(data.sheets[0], first);
        first.onload = update; first.onerror = () => loaded.delete(data.sheets[0]); first.src = data.sheets[0];
        update();
      } else if (data.status === 'pending' || data.status === 'preparing') {
        caption.textContent = '画面预览准备中 · 松手定位';
        retry = setTimeout(load, 4000);
      }
    } catch { /* Time-only scrubbing remains usable when previews are unavailable. */ }
  };
  load();
  return {
    show(time, enabled) { at = time; active = enabled; if (active) update(); },
    destroy() { stopped = true; clearTimeout(retry); loaded.forEach(item => { item.onload = item.onerror = null; }); loaded.clear(); },
  };
};
