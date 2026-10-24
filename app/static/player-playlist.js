(function (scope) {
  'use strict';
  scope.attachPlayerPlaylist = function ({ shell, current, contextIds, load, select, changed, notice, escape, icon, duration }) {
    const panel = shell.querySelector('#episodePanel'), list = shell.querySelector('#episodeList');
    const toggle = shell.querySelector('#episodesButton'), previous = shell.querySelector('#previousEpisode'), next = shell.querySelector('#nextEpisode');
    const search = shell.querySelector('#episodeSearch'), close = shell.querySelector('#episodeClose');
    const description = shell.querySelector('#episodeDescription');
    let items = [current], ready = false, disposed = false, error = false, pending = null, selection = 0, limit = 100;
    const listeners = [];
    const on = (node, event, callback) => { node.addEventListener(event, callback); listeners.push(() => node.removeEventListener(event, callback)); };
    const position = () => items.findIndex(item => Number(item.id) === Number(pending ?? current.id));
    const paint = () => {
      if (disposed) return;
      const at = position();
      previous.disabled = !ready || at <= 0;
      next.disabled = !ready || at < 0 || at >= items.length - 1;
      previous.title = at > 0 ? items[at - 1].file_name : '已经是第一集';
      next.title = at >= 0 && at < items.length - 1 ? items[at + 1].file_name : '已经是最后一集';
      toggle.querySelector('span').textContent = ready ? `选集 ${at + 1}/${items.length}` : error ? '选集 · 重试' : '选集 · 读取中';
      description.textContent = ready ? `${contextIds.length ? '当前列表顺序' : '同频道 · 按名称顺序'} · ${items.length} 个已归档视频` : error ? '列表读取失败，点击重试' : '正在读取已归档视频…';
      shell.querySelector('#episodeRetry').hidden = !error;
      const query = search.value.trim().toLocaleLowerCase();
      const visible = items.filter(item => !query || item.file_name.toLocaleLowerCase().includes(query));
      list.innerHTML = ready ? visible.slice(0, limit).map(item => `<button type="button" class="episode-item ${Number(item.id) === Number(current.id) ? 'is-current' : ''}" data-episode-id="${Number(item.id)}" ${Number(item.id) === Number(current.id) ? 'aria-current="true"' : ''}>
        <span class="episode-cover">${item.thumb_path ? `<img src="/api/media/${Number(item.id)}/thumbnail" loading="lazy" alt="">` : icon('film')}</span>
        <span class="episode-copy"><b>${escape(item.file_name)}</b><small>${Number(item.id) === Number(pending) ? '正在切换…' : Number(item.id) === Number(current.id) ? '正在播放' : duration(item.duration)}</small></span>${Number(item.id) === Number(current.id) ? icon('play') : ''}</button>`).join('') : '';
      shell.querySelector('#episodeEmpty').hidden = !ready || visible.length > 0;
      shell.querySelector('#episodeMore').hidden = visible.length <= limit;
    };
    const setOpen = open => {
      panel.hidden = !open; toggle.setAttribute('aria-expanded', String(open));
      if (!open && panel.contains(document.activeElement)) document.activeElement.blur();
      changed?.();
      if (open) close.focus({ preventScroll: true });
    };
    const choose = async id => {
      id = Number(id);
      if (id === Number(current.id) && pending === null) { setOpen(false); return; }
      const epoch = ++selection;
      pending = id; paint();
      const item = await select(id);
      if (disposed || epoch !== selection) return;
      pending = null;
      if (item) { current = item; setOpen(false); }
      paint(); changed?.();
    };
    const refresh = async () => {
      error = false; ready = false; paint();
      try {
        const all = await load();
        if (disposed) return;
        const rows = new Map(all.map(item => [Number(item.id), item])); rows.set(Number(current.id), current);
        if (contextIds.length) items = [...new Set(contextIds.map(Number))].filter(id => rows.has(id)).map(id => rows.get(id));
        else items = [...rows.values()].filter(item => Number(item.channel_id) === Number(current.channel_id) && Number(item.account_id || 1) === Number(current.account_id || 1))
          .sort((a, b) => a.file_name.localeCompare(b.file_name, 'zh-CN', { numeric: true, sensitivity: 'base' }) || Number(a.id) - Number(b.id));
        if (!items.some(item => Number(item.id) === Number(current.id))) items.unshift(current);
        ready = true;
      } catch { if (!disposed) { error = true; notice?.('播放列表暂时无法读取，可在选集面板重试'); } }
      paint();
    };
    on(toggle, 'click', () => { setOpen(panel.hidden); if (error) void refresh(); });
    on(close, 'click', () => { setOpen(false); toggle.focus({ preventScroll: true }); });
    on(search, 'input', () => { limit = 100; paint(); });
    on(previous, 'click', () => { if (!previous.disabled) void choose(items[position() - 1].id); });
    on(next, 'click', () => { if (!next.disabled) void choose(items[position() + 1].id); });
    on(list, 'click', event => { const item = event.target.closest('[data-episode-id]'); if (item) void choose(item.dataset.episodeId); });
    on(shell.querySelector('#episodeMore'), 'click', () => { limit += 100; paint(); });
    on(shell.querySelector('#episodeRetry'), 'click', () => { void refresh(); });
    void refresh();
    return {
      isOpen: () => !panel.hidden,
      close: () => setOpen(false),
      destroy() { disposed = true; ++selection; listeners.forEach(remove => remove()); },
    };
  };
})(window);
