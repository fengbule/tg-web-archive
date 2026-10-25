/* Server-backed video bookmarks. No upload or download is triggered by a star. */
(function () {
  'use strict';
  const pending = new Set();
  const icon = name => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
  const key = item => `${Number(item.account_id || 1)}:${Number(item.channel_id)}:${Number(item.message_id)}`;
  const source = item => ({ account_id: Number(item.account_id || 1), channel_id: Number(item.channel_id),
    message_id: Number(item.message_id), file_name: item.file_name, channel_title: item.channel_title || '',
    size: Number(item.size || 0), duration: Number(item.duration || 0), width: Number(item.width || 0), height: Number(item.height || 0),
    has_thumbnail: Boolean(item.has_thumbnail || item.thumb_path || item.local_thumbnail),
    ...(item.local_media_id || item.media_id || item.id ? { media_id: Number(item.local_media_id || item.media_id || item.id) } : {}) });
  function button(item, classes = 'icon-action', id = '') {
    const data = source(item), active = Boolean(item.is_favorite);
    return `<button type="button" ${id ? `id="${id}"` : ''} class="favorite-toggle ${classes}" data-favorite-key="${key(data)}" data-favorite-source="${encodeURIComponent(JSON.stringify(data))}" aria-pressed="${active}" aria-label="${active ? '取消收藏' : '收藏视频'}" title="${active ? '已收藏，点击取消' : '收藏视频'}">${icon('star')}</button>`;
  }
  function paint(identity, active) {
    document.querySelectorAll('[data-favorite-key]').forEach(node => {
      if (node.dataset.favoriteKey !== identity) return;
      node.setAttribute('aria-pressed', String(active));
      node.setAttribute('aria-label', active ? '取消收藏' : '收藏视频');
      node.title = active ? '已收藏，点击取消' : '收藏视频';
    });
  }
  document.addEventListener('click', async event => {
    const target = event.target.closest('.favorite-toggle');
    if (!target) return;
    event.preventDefault(); event.stopPropagation();
    const identity = target.dataset.favoriteKey;
    if (pending.has(identity)) return;
    const item = JSON.parse(decodeURIComponent(target.dataset.favoriteSource));
    const active = target.getAttribute('aria-pressed') !== 'true';
    pending.add(identity);
    const buttons = [...document.querySelectorAll('[data-favorite-key]')].filter(node => node.dataset.favoriteKey === identity);
    buttons.forEach(node => { node.disabled = true; node.setAttribute('aria-busy', 'true'); });
    try {
      await api(active ? '/favorites' : `/favorites/${item.account_id}/${item.channel_id}/${item.message_id}`,
        active ? { method: 'PUT', body: JSON.stringify(item) } : { method: 'DELETE' });
      paint(identity, active);
      toast(active ? '已加入视频收藏夹' : '已取消收藏');
      window.dispatchEvent(new CustomEvent('favorites:changed', { detail: { ...item, is_favorite: active } }));
    } catch (error) { toast('收藏未保存：' + error.message); }
    finally { pending.delete(identity); buttons.forEach(node => { node.disabled = false; node.removeAttribute('aria-busy'); }); }
  });
  window.videoFavorites = { button, key };

  let view = null, sequence = 0;
  const valid = current => view === current && activePage === 'favorites' && document.querySelector('#favoriteGrid') === current.grid;
  function card(item) {
    const identity = key(item);
    if (item.downloaded) return `<div class="favorite-entry" data-favorite-entry="${identity}">${window.nebulaMediaCard({ ...item, id: item.media_id }, { select: false })}</div>`;
    const cover = item.has_thumbnail ? `/api/channels/${item.channel_id}/videos/${item.message_id}/thumbnail?account_id=${item.account_id}` : '';
    const labels = { queued: '排队中', downloading: '下载中', retrying: '等待续传', pausing: '暂停中', paused: '继续下载', failed: '重试下载', cancelled: '重新下载' };
    const busy = ['queued', 'downloading', 'retrying', 'pausing'].includes(item.download_status);
    return `<article class="card media-card-v2 favorite-entry" data-favorite-entry="${identity}">
      <div class="media-poster"><div class="poster-fallback">${icon('film')}</div>${cover ? `<img loading="lazy" src="${cover}" alt="" onerror="this.remove()">` : ''}<div class="poster-shade"></div><div class="media-flags"><span class="flag original">待下载</span></div><span class="poster-duration">${Math.floor(item.duration / 60)}:${String(Math.floor(item.duration % 60)).padStart(2, '0')}</span></div>
      <div class="media-card-body"><div class="media-name" title="${esc(item.file_name)}">${esc(item.file_name)}</div><div class="media-sub"><span>${esc(item.channel_title || '未知来源')}</span><span class="dot"></span><span>${fmt(item.size)}</span></div><p class="favorite-account">${esc(item.account_label || '原账号已移除')} · ${date(item.created_at)}</p>
      <div class="media-actions"><button type="button" data-favorite-download="${identity}" ${busy ? 'disabled' : ''}>${icon('download')} ${labels[item.download_status] || '下载到服务器'}</button>${button({ ...item, id: undefined })}</div></div></article>`;
  }
  async function load(current, append = false) {
    if (!valid(current) || (append && current.loading)) return;
    const request = ++current.request;
    current.loading = true;
    const params = new URLSearchParams({ q: document.querySelector('#favoriteSearch').value.trim(),
      state: document.querySelector('#favoriteState').value, sort: document.querySelector('#favoriteSort').value,
      offset: String(append ? current.offset : 0), limit: '60' });
    const account = document.querySelector('#favoriteAccount').value;
    if (account) params.set('account_id', account);
    const more = document.querySelector('#favoriteMore'); more.disabled = true;
    try {
      const data = await api('/favorites?' + params);
      if (!valid(current) || request !== current.request) return;
      if (!append) current.items.clear();
      data.items.forEach(item => current.items.set(key(item), item));
      current.offset = data.next_offset;
      current.grid.innerHTML = [...current.items.values()].map(card).join('');
      window.favoritePlaybackRows = [...current.items.values()].filter(item => item.downloaded).map(item => ({ ...item, id: item.media_id }));
      document.querySelector('#favoriteCount').textContent = `${data.total} 个视频`;
      document.querySelector('#favoriteEmpty').hidden = data.total !== 0;
      document.querySelector('#favoriteError').hidden = true;
      more.hidden = !data.has_more; more.disabled = false;
    } catch (error) {
      if (!valid(current) || request !== current.request) return;
      document.querySelector('#favoriteError').hidden = false;
      document.querySelector('#favoriteError span').textContent = error.message;
      more.disabled = false;
    } finally { if (request === current.request) current.loading = false; }
  }
  window.favoritesPage = function () {
    clearTimeout(view?.searchTimer);
    window.favoritePlaybackRows = [];
    const accounts = [...document.querySelector('#accountSelector').options].map(option => `<option value="${Number(option.value)}">${esc(option.textContent)}</option>`).join('');
    content.innerHTML = `<div class="library-heading favorite-heading"><div><span class="eyebrow">SAVED FOR LATER</span><h3>我的视频收藏</h3><p>点亮星标，留住想看的。随时回来下载或继续播放。</p></div><span class="library-count" id="favoriteCount"></span></div>
      <div class="toolbar favorite-toolbar"><input id="favoriteSearch" maxlength="200" type="search" placeholder="搜索收藏的名称或频道" aria-label="搜索收藏"><select id="favoriteAccount" aria-label="收藏账号"><option value="">所有账号</option>${accounts}</select><select id="favoriteState" aria-label="收藏下载状态"><option value="all">全部收藏</option><option value="downloaded">已下载</option><option value="pending">待下载</option></select><select id="favoriteSort" aria-label="收藏排序"><option value="recent">最近收藏</option><option value="name">按名称</option></select><button class="ghost" id="favoriteRefresh">${icon('refresh')} 刷新</button><button class="ghost" onclick="go('saved')">Telegram 收藏夹 ${icon('arrow')}</button></div>
      <div id="favoriteError" class="notice favorite-error" hidden><span></span><button class="ghost" id="favoriteRetry">重试</button></div><div id="favoriteGrid" class="media-grid"></div><div class="empty-state card" id="favoriteEmpty" hidden><div class="favorite-empty-icon">${icon('star')}</div><h3>把感兴趣的视频留在这里</h3><p>在频道、媒体库或播放器点击星标，即可收藏。也可以调整上方筛选条件。</p><button onclick="go('channels')">去挑选视频</button></div><div class="favorite-more"><button class="ghost" id="favoriteMore" hidden>加载更多收藏</button></div>`;
    const current = view = { id: ++sequence, grid: document.querySelector('#favoriteGrid'), items: new Map(), offset: 0, request: 0, loading: false };
    document.querySelector('#subtitle').textContent = '一键收藏，稍后观看';
    document.querySelector('#favoriteSearch').oninput = () => { clearTimeout(current.searchTimer); current.searchTimer = setTimeout(() => load(current), 250); };
    for (const id of ['favoriteAccount', 'favoriteState', 'favoriteSort']) document.querySelector('#' + id).onchange = () => { void load(current); };
    for (const id of ['favoriteRefresh', 'favoriteRetry']) document.querySelector('#' + id).onclick = () => { void load(current); };
    document.querySelector('#favoriteMore').onclick = () => { void load(current, true); };
    current.grid.onclick = async event => {
      const target = event.target.closest('[data-favorite-download]');
      if (!target) return;
      const item = current.items.get(target.dataset.favoriteDownload);
      if (!item) return;
      target.disabled = true;
      try {
        if (item.download_id && ['paused', 'failed', 'cancelled'].includes(item.download_status)) await api(`/downloads/${item.download_id}/${item.download_status === 'paused' ? 'resume' : 'retry'}`, { method: 'POST' });
        else await api('/downloads', { method: 'POST', body: JSON.stringify([source({ ...item, id: undefined })]) });
        toast('已加入下载任务'); await load(current);
      } catch (error) { toast(error.message); target.disabled = false; }
    };
    timer = setInterval(() => {
      if (valid(current) && !current.loading && current.offset <= 60 && [...current.items.values()].some(item => ['queued', 'downloading', 'retrying', 'pausing'].includes(item.download_status)) && !document.querySelector('#playerShell')) void load(current);
    }, 5000);
    return load(current);
  };
  window.addEventListener('favorites:changed', event => {
    if (valid(view) && !event.detail.is_favorite) void load(view);
  });
})();
