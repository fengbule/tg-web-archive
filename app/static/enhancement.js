/* Optional server-side enhancement. Generation never replaces or selects the original. */
(() => {
  window.enhancementReady = x => x?.enhanced_status === 'ready' && Number(x.enhanced_size) > 0;
  window.pStartEnhanced = async (id, button) => {
    if (button) button.disabled = true;
    try {
      await api(`/media/${id}/enhanced`, {method: 'POST'});
      toast('已加入增强队列，可在播放器中查看进度或取消');
      closeModal(); await play(id);
    } catch (error) { toast(error.message); if (button) button.disabled = false; }
  };
  window.pRemoveEnhanced = async id => {
    if (!confirm('仅移除轻度增强版，原视频会保留。继续吗？')) return;
    try { await api(`/media/${id}/enhanced`, {method:'DELETE'}); toast('增强版已移除，原画保留'); closeModal(); }
    catch (error) { toast(error.message); }
  };
  window.attachEnhancementControls = ({shell, media, quality, select, changed}) => {
    const button = shell.querySelector('#enhanceButton');
    const cancel = shell.querySelector('#enhanceCancel');
    const status = shell.querySelector('#enhanceStatus');
    let stopped = false, timer, epoch = 0, state, acting = false;
    function paint() {
      if (stopped || !state) return;
      const busy = ['queued','processing'].includes(state.status);
      button.disabled = acting || busy;
      button.textContent = state.ready ? (quality() === 'enhanced' ? '切回原画' : '播放轻度增强版')
        : state.status === 'processing' ? `增强中 ${Math.floor(state.progress)}%`
        : state.status === 'queued' ? '增强已排队' : state.status === 'failed' ? '重试轻度增强' : '生成轻度增强版';
      cancel.hidden = !busy;
      cancel.disabled = acting;
      status.textContent = state.ready ? '增强版已就绪 · 原画保留'
        : state.waiting_for_downloads ? '优先下载，空闲后生成'
        : state.status === 'queued' ? (state.error || '等待空闲处理，关闭网页也会继续')
        : state.status === 'processing' ? `正在改善清晰度 · ${Math.floor(state.progress)}%`
        : state.status === 'failed' ? (state.error || '生成失败，可重试') : '改善清晰度 · 原画保留';
      shell.querySelector('#enhanceDownload').hidden = !state.ready;
      shell.querySelector('#enhanceDownload').href = `/api/media/${media().id}/stream?download=true&quality=enhanced`;
    }
    async function refresh() {
      clearTimeout(timer);
      const run = ++epoch, id = media().id;
      try {
        const result = await api(`/media/${id}/enhanced`);
        if (stopped || run !== epoch || media().id !== id) return;
        state = result; changed(state); paint();
        if (['queued','processing'].includes(state.status)) timer = setTimeout(refresh, 1500);
      } catch { if (!stopped && run === epoch) timer = setTimeout(refresh, 5000); }
    }
    button.onclick = async () => {
      if (state?.ready) { select(quality() === 'enhanced' ? 'original' : 'enhanced'); paint(); return; }
      acting = true; button.disabled = true;
      try { await api(`/media/${media().id}/enhanced`, {method:'POST'}); }
      catch (error) { if (!stopped) toast(error.message); }
      finally { acting = false; if (!stopped) void refresh(); }
    };
    cancel.onclick = async () => {
      acting = true; paint();
      try { await api(`/media/${media().id}/enhanced`, {method:'DELETE'}); }
      catch (error) { if (!stopped) toast(error.message); }
      finally { acting = false; if (!stopped) void refresh(); }
    };
    void refresh();
    return {paint, refresh, destroy() { stopped = true; ++epoch; clearTimeout(timer); }};
  };
})();
