/* ============================================================
   NEBULA UI layer
   Overrides the legacy page renderers with the premium console.
   Loaded after app.js so the shared helpers (api, toast, modal,
   fmt, esc, play, accounts, QR) remain available.
   ============================================================ */
(function () {
  'use strict';

  const icon = (name) => `<svg aria-hidden="true"><use href="#i-${name}"></use></svg>`;
  const pct = (a, b) => (b > 0 ? Math.max(0, Math.min(100, (a / b) * 100)) : 0);
  const duration = (value) => {
    const total = Math.max(0, Math.round(Number(value) || 0));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    return h ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${m}:${String(s).padStart(2, '0')}`;
  };
  const greeting = () => {
    const hour = new Date().getHours();
    if (hour < 6) return '夜深了';
    if (hour < 11) return '早上好';
    if (hour < 14) return '中午好';
    if (hour < 18) return '下午好';
    return '晚上好';
  };
  const thumbUrl = (x) => `/api/media/${x.id}/thumbnail?v=3`;
  const smoothReady = (x) => x && x.smooth_status === 'ready' && x.smooth_path;
  const smoothBusy = (x) => x && (x.smooth_status === 'queued' || x.smooth_status === 'processing');
  let libraryPlayback = [];

  function mediaCard(x, opts = {}) {
    const ready = smoothReady(x);
    const busy = smoothBusy(x);
    const progress = Math.round(Number(x.smooth_progress) || 0);
    const flags = [];
    flags.push('<span class="flag original">原画</span>');
    if (x.width && x.height) flags.push(`<span class="flag">${x.width}×${x.height}</span>`);
    if (ready) flags.push('<span class="flag quality">480P 流畅</span>');
    else if (busy) flags.push(`<span class="flag optimizing">优化 ${progress}%</span>`);
    const selected = selectedMedia.has(Number(x.id));
    return `<article class="card media-card-v2" data-media-id="${x.id}">
      <div class="media-poster">
        <div class="poster-fallback">${icon('film')}</div>
        <img loading="lazy" src="${thumbUrl(x)}" alt="Telegram 视频封面" onerror="this.remove()">
        <div class="poster-shade"></div>
        <div class="media-flags">${flags.join('')}</div>
        <span class="poster-duration">${duration(x.duration)}</span>
        <button class="play-fab" type="button" onclick="play(${x.id})" aria-label="播放">${icon('play')}</button>
        ${opts.select === false ? '' : `<label class="select-box ${selected ? 'checked' : ''}" title="选择">
          <input class="media-select" data-id="${x.id}" type="checkbox" ${selected ? 'checked' : ''} onchange="toggleMedia(${x.id},this.checked);this.closest('.select-box').classList.toggle('checked',this.checked)">
          ${icon('check')}
        </label>`}
      </div>
      <div class="media-card-body">
        <div class="media-name" title="${esc(mediaPresentation.title(x))}">${esc(mediaPresentation.title(x))}</div>
        ${mediaPresentation.details(x)}
        <div class="media-sub">
          <span>${esc(x.channel_title || '未知来源')}</span><span class="dot"></span>
          <span>${fmt(x.size)}</span><span class="dot"></span>
          <span>${x.size && x.duration ? ((x.size * 8 / x.duration / 1e6).toFixed(2) + ' Mbps') : duration(x.duration)}</span>
        </div>
        <div class="media-actions">
          <button type="button" onclick="play(${x.id})">${icon('play')} 播放原画</button>
          ${videoFavorites.button(x)}
          <button type="button" class="icon-action" onclick="pDownload(${x.id})" title="另存原画到手机 / 电脑" aria-label="另存原画到手机 / 电脑">${icon('download')}</button>
          <button type="button" class="icon-action" onclick="pMediaMenu(${x.id})" title="更多操作">${icon('chevron')}</button>
        </div>
      </div>
    </article>`;
  }

  window.nebulaMediaCard = mediaCard;

  /* ---------------- dashboard ---------------- */
  window.dashboard = async function () {
    const [d, s, media] = await Promise.all([api('/dashboard'), telegramState(), api('/media?sort=time')]);
    if (activePage !== 'dashboard') return;
    $('#diskBadge').innerHTML = `${icon('cloud')}剩余 ${fmt(d.disk.free)}`;
    const usedPct = pct(d.disk.used, d.disk.total);
    const recent = media.slice(0, 4);
    const accountName = s.authorized ? (s.name || '已连接账号') : '尚未连接 Telegram';
    const onboarding = s.authorized ? '' : `<div class="card" style="padding:22px;margin-top:18px;border-color:rgba(109,139,255,.35);background:linear-gradient(135deg,rgba(109,139,255,.14),rgba(12,18,33,.85))">
      <div class="section-title" style="margin-bottom:6px">${icon('shield')} 还差一步：连接 Telegram</div>
      <p class="muted" style="font-size:12.5px;max-width:640px">连接后可浏览已加入频道的视频、批量归档到本地，并随时原画播放或下载。验证码与两步验证密码只用于当次登录，不会保存。</p>
      <div class="actions"><button onclick="go('telegram')">立即连接${icon('arrow')}</button><button class="ghost" onclick="go('settings')">查看部署信息</button></div>
    </div>`;
    content.innerHTML = `
      <section class="hero">
        <div class="hero-copy">
          <span class="eyebrow">PRIVATE MEDIA CONSOLE</span>
          <h3>${greeting()}，${esc(accountName)}</h3>
          <p>${s.authorized ? '账号已连接。你的频道视频、下载任务与本地媒体库都在这里。' : '连接 Telegram 账号后，开始把喜欢的频道视频归档到自己的服务器。'}</p>
        </div>
        <div class="hero-actions">
          <button onclick="go('channels')">${icon('tv')} 浏览频道</button>
          <button class="ghost" onclick="go('library')">${icon('film')} 打开媒体库</button>
        </div>
      </section>
      ${onboarding}
      <div class="stat-grid">
        <div class="card stat-card"><div class="stat-ico">${icon('film')}</div><div class="stat-label">本地视频</div><div class="stat-value">${d.video_count}</div><div class="stat-sub">占用 ${fmt(d.media_bytes)}</div></div>
        <div class="card stat-card"><div class="stat-ico">${icon('cloud')}</div><div class="stat-label">磁盘剩余</div><div class="stat-value">${fmt(d.disk.free)}</div><div class="stat-sub">总容量 ${fmt(d.disk.total)}</div></div>
        <div class="card stat-card"><div class="stat-ico">${icon('download')}</div><div class="stat-label">活跃任务</div><div class="stat-value">${d.active_downloads}</div><div class="stat-sub">双并发 · 断点续传</div></div>
        <div class="card stat-card"><div class="stat-ico">${icon('zap')}</div><div class="stat-label">临时文件</div><div class="stat-value">${fmt(d.temp_bytes)}</div><div class="stat-sub">保护预留 ${fmt(d.reserve_bytes)}</div></div>
      </div>
      <div class="card storage-card">
        <div class="storage-ring" style="--used:${usedPct}%"><div><b>${usedPct.toFixed(0)}%</b><small>磁盘使用</small></div></div>
        <div class="storage-copy">
          <h3>存储空间</h3>
          <p>已使用 ${fmt(d.disk.used)}，剩余 ${fmt(d.disk.free)}。达到保护线后新下载会自动暂停，不会写满磁盘。</p>
          <div class="progress storage-bar"><i style="width:${usedPct}%"></i></div>
          <div class="storage-legend"><span><i></i>已使用 ${fmt(d.disk.used)}</span><span><i style="background:#2a3a5c"></i>可用 ${fmt(d.disk.free)}</span><span><i style="background:#ffb020"></i>预留 ${fmt(d.reserve_bytes)}</span></div>
        </div>
      </div>
      <section class="section">
        <div class="section-head">
          <div class="section-title">${icon('film')} 最近归档</div>
          <button class="link-btn" onclick="go('library')">查看全部 ${media.length} 个视频 ${icon('arrow')}</button>
        </div>
        ${recent.length ? `<div class="recent-grid">${recent.map((x) => mediaCard(x, { select: false })).join('')}</div>` : `<div class="empty-state"><h3>媒体库还是空的</h3><p>去“频道视频”选择想保存的视频，下载完成后会自动出现在这里，并生成可拖动的原画播放索引。</p><button onclick="go('channels')">浏览频道视频</button></div>`}
      </section>`;
  };

  /* ---------------- library ---------------- */
  window.library = function () {
    libraryPlayback = [];
    selectedMedia.clear();
    content.innerHTML = `
      <div class="library-heading"><div><span class="eyebrow">SERVER MEDIA</span><h3>服务器媒体库</h3><p>视频已保存在服务器。原画播放，或另存到手机 / 电脑。</p></div><span class="library-count" id="libraryCount"></span></div>
      <div class="toolbar">
        <input id="mediaSearch" placeholder="搜索视频名称或频道" onkeydown="if(event.key==='Enter')loadMedia()">
        <select id="mediaSort" onchange="loadMedia()">
          <option value="time">最新归档</option><option value="name">按名称</option><option value="size">按大小</option>
        </select>
        <button class="ghost p-toolbar-search" onclick="loadMedia()">${icon('search')} 搜索</button>
        <label><input id="selectAllMedia" type="checkbox" onchange="toggleAllMedia(this.checked)"> 全选</label>
        <button id="batchDownloadBtn" class="ghost" onclick="pDownloadSelected()" disabled>${icon('download')} 另存到本机 (<span>0</span>)</button>
        <button id="deleteSelectedBtn" class="danger" onclick="deleteSelectedMedia()" disabled>${icon('x')} 删除选中 (<span>0</span>)</button>
        <button class="ghost" id="refreshCoversButton" onclick="pRefreshCovers(this)">同步 TG 封面</button>
        <button class="ghost p-clear-btn" onclick="clearAllMedia()" title="清空媒体库">${icon('refresh')} 清空</button>
      </div>
      <div id="mediaGrid" class="media-grid"></div>`;
    loadMedia();
  };

  window.loadMedia = async function () {
    const q = encodeURIComponent($('#mediaSearch')?.value || '');
    const sort = $('#mediaSort')?.value || 'time';
    const xs = await api(`/media?q=${q}&sort=${sort}`);
    const box = $('#mediaGrid');
    if (!box) return;
    libraryPlayback = xs;
    if ($('#libraryCount')) $('#libraryCount').textContent = `${xs.length} 个视频`;
    const ids = new Set(xs.map((x) => Number(x.id)));
    [...selectedMedia].forEach((id) => { if (!ids.has(id)) selectedMedia.delete(id); });
    box.innerHTML = xs.length
      ? xs.map((x) => mediaCard(x)).join('')
      : `<div class="empty-state" style="grid-column:1/-1"><h3>没有找到视频</h3><p>尝试换一个关键词，或先去频道下载视频。</p><button onclick="go('channels')">浏览频道</button></div>`;
    updateMediaSelection();
  };

  window.pRefreshCovers = async function (button) {
    button.disabled = true;
    try {
      let state = await api('/media/covers/refresh', { method: 'POST' });
      while (state.status === 'running') {
        button.textContent = `同步封面 ${state.done} / ${state.total}`;
        await new Promise(resolve => setTimeout(resolve, 1000));
        state = await api('/media/covers/refresh');
      }
      if (state.status !== 'completed') throw new Error('任务已中断，请重新同步');
      toast(`封面同步完成：更新 ${state.updated} 个，沿用 ${state.retained} 个 TG 原封面，${state.fallback} 个保留本地图，${state.unavailable} 个暂不可用`);
      if (activePage === 'library') { await loadMedia(); document.querySelectorAll('#mediaGrid .media-poster img').forEach(image => { image.src += '&sync=' + Date.now(); }); }
    } catch (error) { toast('封面同步未完成：' + error.message); }
    finally { button.disabled = false; button.textContent = '同步 TG 封面'; }
  };

  window.updateMediaSelection = function () {
    const count = selectedMedia.size;
    const dl = $('#batchDownloadBtn');
    if (dl) { dl.disabled = !count; dl.querySelector('span').textContent = count; }
    const del = $('#deleteSelectedBtn');
    if (del) { del.disabled = !count; del.querySelector('span').textContent = count; }
    const all = $('#selectAllMedia');
    const boxes = [...document.querySelectorAll('.media-select')];
    if (all) {
      all.checked = boxes.length > 0 && boxes.every((x) => x.checked);
      all.indeterminate = boxes.some((x) => x.checked) && !boxes.every((x) => x.checked);
    }
  };

  window.pDownloadSelected = function () {
    if (!selectedMedia.size) return toast('请先选择视频');
    const ids = [...selectedMedia].join(',');
    const a = document.createElement('a');
    a.href = `/api/media/download-zip?ids=${encodeURIComponent(ids)}`;
    a.download = '';
    document.body.appendChild(a);
    a.click();
    a.remove();
    toast(`正在打包 ${selectedMedia.size} 个视频，浏览器会稍后开始下载`);
  };

  window.pDownload = function (id, quality) {
    const q = quality === 'smooth' ? '&quality=smooth' : '';
    const a = document.createElement('a');
    a.href = `/api/media/${id}/stream?download=true${q}`;
    a.download = '';
    document.body.appendChild(a);
    a.click();
    a.remove();
    toast('已请求本机下载，请在浏览器下载列表查看');
  };

  window.pMediaMenu = async function (id) {
    const x = await api('/media/' + id);
    const ready = smoothReady(x);
    const busy = smoothBusy(x);
    modal(`<h3 style="margin-bottom:4px">${esc(x.file_name)}</h3>
      <p class="muted" style="font-size:12px">${esc(x.channel_title)} · ${fmt(x.size)} · ${x.width}×${x.height} · ${duration(x.duration)}</p>
      <div class="actions" style="display:grid;grid-template-columns:1fr 1fr;gap:9px;margin-top:18px">
        <button onclick="closeModal();play(${id},'original')">${icon('play')} 原画播放</button>
        <button class="ghost" onclick="pDownload(${id})">${icon('download')} 另存原画到手机 / 电脑</button>
        ${ready ? `<button class="ghost" onclick="closeModal();play(${id},'smooth')">${icon('zap')} 播放 480P 流畅版</button><button class="ghost" onclick="pDownload(${id},'smooth')">${icon('download')} 下载 480P</button>` : busy ? `<button class="ghost" disabled>${icon('zap')} 流畅版生成中 ${Math.round(x.smooth_progress || 0)}%</button>` : `<button class="ghost" onclick="pStartSmooth(${id},this)">${icon('zap')} 生成 480P 流畅版</button>`}
        <button class="ghost" onclick="closeModal();sendMediaToSaved(${id})">${icon('star')} 上传收藏夹</button>
        <button class="ghost" onclick="closeModal();renameMedia(${id},'${encodeURIComponent(x.file_name)}')">${icon('film')} 重命名</button>
        <button class="danger" style="grid-column:1/-1" onclick="closeModal();deleteMedia(${id})">${icon('x')} 永久删除</button>
      </div>`);
  };

  window.pStartSmooth = async function (id, button) {
    try {
      if (button) { button.disabled = true; button.textContent = '正在加入队列…'; }
      await api(`/media/${id}/smooth`, { method: 'POST' });
      toast('已开始生成 480P 流畅版，可在播放器中查看进度');
      if (button) { button.textContent = '生成中…'; }
      pWatchSmooth(id, button);
    } catch (e) { toast(e.message); if (button) button.disabled = false; }
  };

  function pWatchSmooth(id, button) {
    clearInterval(button && button._smoothTimer);
    const timer = setInterval(async () => {
      try {
        const s = await api(`/media/${id}/smooth`);
        if (button) button.textContent = s.ready ? '流畅版已就绪' : `生成中 ${Math.round(s.progress)}%`;
        if (s.ready || s.status === 'failed') {
          clearInterval(timer);
          if (s.status === 'failed') toast(s.error || '流畅版生成失败，可能是编码不受支持');
          else toast('480P 流畅版已生成，可随时切换');
        }
      } catch { clearInterval(timer); }
    }, 2000);
    if (button) button._smoothTimer = timer;
  }

  /* ---------------- player ---------------- */
  let playerRequest = 0;
  window.play = async function (id, preferred) {
    const request = ++playerRequest;
    window.pClosePlayer?.();
    let [x, playback] = await Promise.all([
      api('/media/' + id),
      api(`/media/${id}/playback`).catch(() => ({ original: { type: 'file', url: `/api/media/${id}/stream?quality=original` } })),
    ]);
    if (request !== playerRequest) return;
    let smooth = smoothReady(x);
    let quality = preferred === 'smooth' && smooth ? 'smooth' : 'original';
    let hls = null, direct = false, sourceRun = 0, closed = false;
    let restorePosition = 0, resumeOnReady = true, firstLoad = true;
    let smoothTimer = null, saveAt = 0, speed = 1, episodeRequest = 0;
    const contextIds = activePage === 'favorites' ? (window.favoritePlaybackRows || []).map(item => Number(item.id)) : activePage === 'library' ? [...document.querySelectorAll('#mediaGrid .media-card-v2')].map(card => Number(card.dataset.mediaId))
      : activePage === 'channels' ? [...document.querySelectorAll('.catalog-card[data-local-media-id]:not([hidden])')].map(card => Number(card.dataset.localMediaId)) : [];
    const contextRows = activePage === 'favorites' ? (window.favoritePlaybackRows || []) : activePage === 'library' ? libraryPlayback : null;
    modal(`<div class="video-modal player-shell" id="playerShell"><div class="player-viewport" id="playerViewport">
      <div class="player-top">
        <div class="player-title"><span class="player-eyebrow">NOW PLAYING</span><h3 title="${esc(x.file_name)}">${esc(mediaPresentation.title(x))}</h3><p>${esc(x.channel_title)} · ${x.width} × ${x.height} · ${fmt(x.size)}</p></div>
        <span class="lock-status" id="lockStatus" hidden></span>
        ${videoFavorites.button(x, 'ctl', 'playerFavorite')}
        <button class="quality-btn" id="qualityButton" data-lock-disable type="button" ${smooth ? '' : 'disabled'} title="切换原画 / 流畅版">${quality === 'smooth' ? '480P 流畅' : '原画'}</button>
        <button class="ctl" id="playerClose" data-lock-disable type="button" aria-label="关闭播放器">${icon('x')}</button>
      </div>
      <div class="player-stage" id="playerStage">
        <video id="player" playsinline webkit-playsinline preload="auto" poster="${thumbUrl(x)}"></video>
        <div class="player-spinner" id="playerSpinner"></div>
        <div class="seek-preview" id="seekPreview" hidden><div class="seek-frame" role="img" aria-label="目标时间附近的画面预览" hidden></div><b></b><small>松手后继续 · 横滑可精细定位</small></div>
        <div class="buffer-status" id="bufferStatus" hidden>正在准备原画…</div>
      </div>
      <div class="player-controls">
        <div class="seek-times"><span id="elapsedTime">0:00</span><span id="gestureHint">轻点显隐按钮 · 横滑快进</span><span id="totalTime">${duration(x.duration)}</span></div>
        <div class="seek-wrap" id="seekWrap">
          <div class="seek-track"><div class="seek-buffer" id="seekBuffer"></div><div class="seek-played" id="seekPlayed"></div></div>
          <div class="seek-thumb" id="seekThumb"></div>
          <input class="seek-input" id="seekInput" type="range" min="0" max="10000" value="0" step="1" aria-label="播放进度" aria-valuetext="0:00">
        </div>
        <div class="controls-row">
          <div class="transport-controls">
            <button class="ctl primary-play" id="playToggle" type="button" aria-label="播放" title="播放">${icon('play')}</button>
            <button class="ctl skip-button" id="skipBack" type="button" aria-label="后退 10 秒" title="后退 10 秒">${icon('refresh')}<span>10</span></button>
            <button class="ctl skip-button" id="skipForward" type="button" aria-label="前进 10 秒" title="前进 10 秒">${icon('refresh')}<span>10</span></button>
            <span class="time" id="timeLabel">0:00 / ${duration(x.duration)}</span>
          </div>
          <div class="player-tools">
            <div class="volume-wrap" id="volumeWrap"><input id="volumeInput" type="range" min="0" max="1" step="0.05" value="1" aria-label="音量"></div>
            <button class="ctl" id="muteToggle" type="button" aria-label="静音">${icon('volume')}</button>
            <button class="ctl" id="speedButton" type="button" aria-label="播放速度">1×</button>
            <button class="ctl" id="lockButton" type="button" aria-label="锁定界面方向" aria-pressed="false" title="锁定界面方向，仍可快进和选集">${icon('unlock')}</button>
            <button class="ctl" id="pipButton" data-lock-disable type="button" aria-label="画中画">${icon('pip')}</button>
            <a class="ctl" id="downloadButton" data-lock-disable href="/api/media/${id}/stream?download=true" download title="下载原画到本机" aria-label="下载到本机">${icon('download')}</a>
            <button class="ctl" id="fullscreenButton" data-lock-disable type="button" aria-label="全屏">${icon('expand')}</button>
          </div>
        </div>
        <div class="player-navigation">
          <button class="episode-step" id="previousEpisode" type="button" disabled>${icon('previous')}<span>上一集</span></button>
          <button class="episode-picker" id="episodesButton" type="button" aria-controls="episodePanel" aria-expanded="false">${icon('list')}<span>选集 · 读取中</span></button>
          <button class="episode-step" id="nextEpisode" type="button" disabled><span>下一集</span>${icon('next')}</button>
        </div>
      </div>
      <section class="player-episodes" id="episodePanel" hidden aria-label="播放列表">
        <div class="episode-heading"><div><b>播放列表</b><p id="episodeDescription">正在读取…</p></div><button class="ctl" id="episodeClose" type="button" aria-label="关闭选集">${icon('x')}</button></div>
        <input id="episodeSearch" type="search" placeholder="搜索集数或视频名称" aria-label="搜索选集">
        <div class="episode-list" id="episodeList"></div><p class="episode-empty" id="episodeEmpty" hidden>没有匹配的视频</p>
        <button class="ghost" id="episodeRetry" type="button" hidden>重新读取列表</button><button class="ghost" id="episodeMore" type="button" hidden>显示更多</button>
      </section>
      <div class="player-foot"><div class="player-meta"><span class="original-pill" id="metaQuality">${quality === 'smooth' ? '480P 流畅' : '原画 · 原始编码'}</span><span id="metaBitrate"></span><span>音画同步播放</span></div><div class="player-actions"><button class="ghost" id="smoothButton" type="button">${smooth ? '切换流畅版' : '生成流畅版'}</button><a id="originalDownloadLink" href="/api/media/${id}/stream?download=true" download>${icon('download')} 下载原文件</a></div></div>
      <div class="player-error" id="playerError" role="status" hidden></div>
    </div></div>`, true);
    const video = $('#player'), stage = $('#playerStage'), spinner = $('#playerSpinner');
    const buffer = $('#bufferStatus'), playToggle = $('#playToggle');
    const seek = $('#seekInput'), played = $('#seekPlayed'), buffered = $('#seekBuffer'), thumb = $('#seekThumb');
    const qualityButton = $('#qualityButton'), smoothButton = $('#smoothButton'), downloadButton = $('#downloadButton');
    let scrubber, queue;
    const loading = attachPlayerBuffer({ video, node: buffer, spinner });
    const shell = $('#playerShell');
    const controls = attachPlayerControls({ shell, stage, video, scrubbing: () => scrubber?.dragging(), interacting: () => queue?.isOpen() });
    const locker = attachPlayerLock({ shell, button: $('#lockButton'), changed: () => controls.show(), notice: toast });
    let storyboard = createSeekPreview(id, $('#seekPreview'));
    const preview = (at, active = false) => {
      const d = Number(video.duration) || Number(x.duration) || 0;
      const percentage = pct(at, d);
      played.style.width = `${percentage}%`; thumb.style.left = `${percentage}%`;
      seek.value = String(Math.round(percentage * 100));
      seek.setAttribute('aria-valuetext', `${duration(at)} / ${duration(d)}`);
      $('#elapsedTime').textContent = duration(at);
      $('#timeLabel').textContent = `${duration(at)} / ${duration(d)}`;
      $('#seekWrap').classList.toggle('active', active);
      $('#seekPreview').hidden = !active;
      if (active) $('#seekPreview b').textContent = duration(at);
      storyboard.show(at, active);
    };
    const paint = () => {
      if (closed || scrubber?.dragging()) return;
      preview(Number(video.currentTime) || 0);
      const d = Number(video.duration) || Number(x.duration) || 0;
      let end = Number(video.currentTime) || 0;
      for (let n = 0; n < video.buffered.length; n++) {
        if (video.buffered.start(n) <= end + .5 && video.buffered.end(n) >= end) end = video.buffered.end(n);
      }
      buffered.style.width = `${pct(end, d)}%`;
    };
    const error = message => { $('#playerError').hidden = false; $('#playerError').textContent = message; };
    const updateQuality = () => {
      qualityButton.textContent = quality === 'smooth' ? '480P 流畅' : '原画';
      $('#metaQuality').textContent = quality === 'smooth' ? '480P 流畅' : '原画 · 原始编码';
      const size = quality === 'smooth' ? x.smooth_size : x.size;
      $('#metaBitrate').textContent = size && x.duration ? (size * 8 / x.duration / 1e6).toFixed(2) + ' Mbps' : '';
      downloadButton.href = `/api/media/${id}/stream?download=true${quality === 'smooth' ? '&quality=smooth' : ''}`;
      downloadButton.title = quality === 'smooth' ? '下载流畅版到本机' : '下载原画到本机';
    };
    const mount = (at, resume) => {
      const run = ++sourceRun;
      restorePosition = at; resumeOnReady = resume;
      hls?.destroy(); hls = null;
      video.pause(); video.removeAttribute('src'); video.load();
      loading.reset(at);
      const original = quality === 'original' && !direct && playback.original.type === 'hls';
      const url = original ? playback.original.url : `/api/media/${id}/stream?quality=${quality}`;
      const agent = navigator.userAgent;
      const nativePreferred = /iP(?:hone|ad|od)/.test(agent) || (/Safari/.test(agent) && !/Chrome|Chromium|Edg|OPR|Android/.test(agent));
      if (original && !nativePreferred && window.Hls?.isSupported()) {
        hls = new Hls({ autoStartLoad: false, startPosition: at, enableWorker: true, progressive: true,
          maxBufferLength: 16, maxMaxBufferLength: 32, maxBufferSize: 24 * 1024 * 1024, backBufferLength: 30 });
        const instance = hls;
        loading.bind(instance, Hls.Events);
        instance.on(Hls.Events.MEDIA_ATTACHED, () => { if (run === sourceRun) instance.loadSource(url); });
        instance.on(Hls.Events.MANIFEST_PARSED, () => { if (run === sourceRun) instance.startLoad(at); });
        instance.on(Hls.Events.ERROR, (_event, data) => {
          if (run !== sourceRun || closed || !data.fatal) return;
          direct = true;
          mount(restorePosition ?? video.currentTime, restorePosition !== null ? resumeOnReady : !video.paused && !video.ended);
        });
        instance.attachMedia(video);
      } else {
        video.src = original && video.canPlayType('application/vnd.apple.mpegurl') ? url : `/api/media/${id}/stream?quality=${quality}`;
        video.load();
      }
      updateQuality();
    };
    const changeEpisode = async target => {
      const epoch = ++episodeRequest;
      const resume = restorePosition !== null ? resumeOnReady : !video.paused;
      try {
        const [item, info] = await Promise.all([
          api('/media/' + target),
          api(`/media/${target}/playback`).catch(() => ({ original: { type: 'file', url: `/api/media/${target}/stream?quality=original` } })),
        ]);
        if (closed || epoch !== episodeRequest) return null;
        try { localStorage.setItem('tvm-pos-' + id, String(restorePosition ?? video.currentTime)); } catch {}
        clearInterval(smoothTimer); smoothTimer = null;
        storyboard.destroy();
        id = Number(target); x = item; playback = info;
        shell.dataset.mediaId = String(id);
        smooth = smoothReady(x); quality = 'original'; direct = false; firstLoad = true; saveAt = 0;
        shell.querySelector('.player-title h3').textContent = mediaPresentation.title(x);
        shell.querySelector('.player-title h3').title = x.file_name;
        $('#playerFavorite').outerHTML = videoFavorites.button(x, 'ctl', 'playerFavorite');
        shell.querySelector('.player-title p').textContent = `${x.channel_title} · ${x.width} × ${x.height} · ${fmt(x.size)}`;
        $('#totalTime').textContent = duration(x.duration);
        video.poster = thumbUrl(x);
        qualityButton.disabled = !smooth;
        smoothButton.disabled = false; smoothButton.textContent = smooth ? '切换流畅版' : '生成流畅版';
        $('#originalDownloadLink').href = `/api/media/${id}/stream?download=true`;
        $('#playerError').hidden = true; $('#seekPreview').hidden = true;
        storyboard = createSeekPreview(id, $('#seekPreview'));
        buffered.style.width = '0%';
        let saved = 0;
        try { saved = Number(localStorage.getItem('tvm-pos-' + id) || 0); } catch {}
        mount(saved > 5 && saved < Number(x.duration) - 10 ? saved : 0, resume);
        preview(saved > 5 && saved < Number(x.duration) - 10 ? saved : 0);
        controls.show();
        return x;
      } catch (error) {
        if (!closed && epoch === episodeRequest) toast('切换失败，当前视频已保留：' + error.message);
        return null;
      }
    };
    shell.dataset.mediaId = String(id);
    queue = attachPlayerPlaylist({ shell, current: x, contextIds, load: () => contextRows?.length ? Promise.resolve(contextRows) : api(`/media?channel_id=${Number(x.channel_id)}&sort=name`), select: changeEpisode,
      changed: () => controls.show(), notice: toast, escape: esc, icon, duration });
    video.addEventListener('loadedmetadata', () => {
      if (closed) return;
      video.playbackRate = speed;
      const at = restorePosition; restorePosition = null;
      if (at !== null && at > 0 && Number.isFinite(video.duration)) video.currentTime = Math.min(at, video.duration - .05);
      if (firstLoad && at > 5) toast(`已继续上次播放 · ${duration(at)}`);
      firstLoad = false;
      if (resumeOnReady) video.play().catch(() => {});
      paint();
    });
    video.addEventListener('timeupdate', () => {
      paint();
      if (!scrubber?.dragging() && Date.now() - saveAt > 4000 && video.currentTime > 5) {
        saveAt = Date.now();
        try { localStorage.setItem('tvm-pos-' + id, String(video.currentTime)); } catch {}
      }
    });
    video.addEventListener('progress', paint);
    const ready = () => { if (!closed) loading.hide(); };
    const syncPlayButton = () => {
      const playing = !video.paused && !video.ended;
      playToggle.innerHTML = icon(playing ? 'pause' : 'play');
      playToggle.setAttribute('aria-label', playing ? '暂停' : '播放');
      playToggle.title = playing ? '暂停' : '播放';
    };
    video.addEventListener('play', syncPlayButton);

    video.addEventListener('pause', syncPlayButton);
    video.addEventListener('ended', syncPlayButton);
    video.addEventListener('error', () => {
      if (closed || !video.error) return;
      if (quality === 'original' && hls && !direct) { direct = true; mount(restorePosition ?? video.currentTime, restorePosition !== null ? resumeOnReady : !video.paused); return; }
      ready(); error('原画暂时无法播放。可重试、下载原文件，或手动切换流畅版；画质不会自动降低。');
    });
    const toggle = () => { if (video.paused) video.play().catch(() => {}); else video.pause(); };
    playToggle.onclick = toggle;
    const skip = seconds => { video.currentTime = Math.max(0, Math.min((video.duration || 0) - .05, video.currentTime + seconds)); paint(); };
    $('#skipBack').onclick = () => skip(-10); $('#skipForward').onclick = () => skip(10);
    scrubber = attachMediaScrubber({ video, input: seek, stage, preview,
      finish: () => { $('#seekPreview').hidden = true; $('#seekWrap').classList.remove('active'); paint(); },
      changed: at => { if (hls && hls.loadingEnabled === false) hls.startLoad(at); },
    });
    $('#muteToggle').onclick = () => { video.muted = !video.muted; };
    video.addEventListener('volumechange', () => { if (!closed) $('#muteToggle').classList.toggle('is-muted', video.muted || video.volume === 0); });
    $('#volumeInput').oninput = event => { video.volume = Number(event.target.value); video.muted = false; };
    $('#muteToggle').onmouseenter = () => $('#volumeWrap').classList.add('open');
    $('#volumeWrap').onmouseleave = () => $('#volumeWrap').classList.remove('open');
    const rates = [1, 1.25, 1.5, 2, .75];
    $('#speedButton').onclick = () => { speed = rates[(rates.indexOf(speed) + 1) % rates.length]; video.playbackRate = speed; $('#speedButton').textContent = speed + '×'; };
    $('#pipButton').onclick = async () => {
      try { if (document.pictureInPictureElement) await document.exitPictureInPicture(); else await video.requestPictureInPicture(); }
      catch { toast('当前浏览器不支持画中画'); }
    };
    $('#fullscreenButton').onclick = async () => {
      try { if (document.fullscreenElement) await document.exitFullscreen(); else if ($('#playerShell').requestFullscreen) await $('#playerShell').requestFullscreen(); else video.webkitEnterFullscreen?.(); }
      catch { toast('当前浏览器不支持全屏'); }
    };
    const setQuality = next => {
      if (closed || next === quality || (next === 'smooth' && !smooth)) return;
      const at = restorePosition ?? video.currentTime;
      const resume = restorePosition !== null ? resumeOnReady : !video.paused;
      quality = next; $('#playerError').hidden = true;
      mount(at, resume);
      toast(next === 'original' ? '已切回原画' : '已切换流畅版');
    };
    window.pSetQuality = setQuality;
    qualityButton.onclick = () => setQuality(quality === 'original' ? 'smooth' : 'original');
    smoothButton.onclick = async () => {
      if (smooth) { setQuality('smooth'); return; }
      const smoothId = id;
      smoothButton.disabled = true;
      try {
        await api(`/media/${smoothId}/smooth`, { method: 'POST' });
        if (closed || id !== smoothId) return;
        smoothButton.textContent = '生成中…';
        smoothTimer = setInterval(async () => {
          try {
            const state = await api(`/media/${smoothId}/smooth`);
            if (closed || id !== smoothId) return;
            smoothButton.textContent = `生成中 ${Math.round(state.progress)}%`;
            if (state.ready || state.status === 'failed') {
              clearInterval(smoothTimer); smoothButton.disabled = false;
              smoothButton.textContent = state.ready ? '切换流畅版' : '重新生成流畅版';
              if (state.ready) { smooth = true; x.smooth_size = state.size; qualityButton.disabled = false; }
              else toast(state.error || '生成失败，请重试');
            }
          } catch { if (!closed && id === smoothId) { clearInterval(smoothTimer); smoothButton.disabled = false; } }
        }, 2000);
      } catch (ex) { if (!closed && id === smoothId) { toast(ex.message); smoothButton.disabled = false; } }
    };
    const backdrop = event => { if (event.target.id === 'modal' && !locker.isLocked()) close(); };
    const close = () => {
      if (closed) return;
      closed = true; sourceRun++; episodeRequest++; clearInterval(smoothTimer); queue.destroy(); locker.destroy(); controls.destroy(); scrubber.destroy(); storyboard.destroy(); loading.destroy();
      try { localStorage.setItem('tvm-pos-' + id, String(restorePosition ?? video.currentTime)); } catch {}
      hls?.destroy(); hls = null; video.pause(); video.removeAttribute('src'); video.load();
      document.removeEventListener('keydown', keyHandler); $('#modal').removeEventListener('click', backdrop);
      if (window.pClosePlayer === close) window.pClosePlayer = null;
      if (window.pSetQuality === setQuality) window.pSetQuality = null;
      closeModal();
    };
    const keyHandler = event => {
      if (closed) return;
      if (event.key === 'Escape') {
        if (queue.isOpen()) queue.close();
        else if (locker.isLocked()) void locker.setLocked(false);
        else close();
        return;
      }
      if (event.target.matches('input,textarea,select')) return;
      if (event.code === 'Space') { event.preventDefault(); toggle(); }
      else if (event.code === 'ArrowLeft') { event.preventDefault(); skip(-5); }
      else if (event.code === 'ArrowRight') { event.preventDefault(); skip(5); }
      else if (event.key.toLowerCase() === 'f' && !locker.isLocked()) $('#fullscreenButton').click();
      else if (event.key.toLowerCase() === 'm') video.muted = !video.muted;
    };
    window.pClosePlayer = close; $('#playerClose').onclick = close;
    $('#modal').addEventListener('click', backdrop); document.addEventListener('keydown', keyHandler);
    let saved = 0;
    try { saved = Number(localStorage.getItem('tvm-pos-' + id) || 0); } catch {}
    mount(saved > 5 && saved < Number(x.duration) - 10 ? saved : 0, true);
  };

  /* ---------------- downloads ---------------- */
  window.downloads = async function () {
    const statusText = { queued: '等待下载', downloading: '正在下载', pausing: '正在暂停', retrying: '等待续传', completed: '已完成', failed: '失败', cancelled: '已取消', paused: '已暂停' };
    async function render() {
      const xs = await api('/downloads');
      if (activePage !== 'downloads') return;
      const active = xs.filter((x) => ['queued', 'downloading', 'retrying', 'pausing', 'paused'].includes(x.status));
      const done = xs.filter((x) => ['completed', 'failed', 'cancelled'].includes(x.status));
      const row = (x) => {
        const pc = pct(x.downloaded_bytes, x.total_bytes);
        const speed = x.speed ? fmt(x.speed) + '/s' : '';
        const remain = x.speed > 0 && x.total_bytes > 0 ? duration((x.total_bytes - x.downloaded_bytes) / x.speed) : '';
        return `<div class="card dl-row">
          <div class="dl-ico">${icon(x.status === 'completed' ? 'check' : 'download')}</div>
          <div class="dl-main">
            <div class="dl-title" title="${esc(x.file_name)}">${esc(x.file_name)}</div>
            <div class="dl-meta"><span class="dl-status ${x.status}">${statusText[x.status] || x.status}</span><span>${esc(x.channel_title || '')}</span><span><b>${fmt(x.downloaded_bytes)}</b> / ${fmt(x.total_bytes)}</span>${speed ? `<span>${speed}</span>` : ''}${remain ? `<span>剩余约 ${remain}</span>` : ''}</div>
            <div class="dl-progress"><div class="progress"><i style="width:${pc}%"></i></div><span class="dl-pct">${pc.toFixed(1)}%</span></div>
            ${x.error ? `<div class="dl-meta" style="color:#ff8d9e">${esc(x.error)}</div>` : ''}
          </div>
          <div class="dl-actions">
            ${['queued', 'downloading', 'retrying'].includes(x.status) ? `<button class="ghost" onclick="pauseTask(${x.id})">暂停</button>` : ''}
            ${x.status === 'pausing' ? '<span class="muted" style="font-size:11px">请稍候…</span>' : ''}
            ${x.status === 'paused' ? `<button onclick="resumeTask(${x.id})">继续</button>` : ''}
            ${['failed', 'cancelled'].includes(x.status) ? `<button onclick="retryTask(${x.id})">重试</button>` : ''}
            ${['queued', 'downloading', 'retrying', 'pausing', 'paused'].includes(x.status) ? `<button class="ghost-danger ghost" onclick="cancelTask(${x.id})">取消</button>` : ''}
            ${x.status === 'completed' ? `<button class="ghost" onclick="go('library')">媒体库</button>` : ''}
          </div>
        </div>`;
      };
      content.innerHTML = `<div class="notice"><b>下载到服务器 · 支持暂停与续传</b><span>关闭手机或电脑上的网页，服务器仍会继续下载。完成后到“服务器媒体库”播放；如需保存到自己的设备，再点“另存到本机”。</span></div>
        ${active.length ? `<div class="section-head"><div class="section-title">${icon('download')} 进行中 · ${active.length}</div></div><div class="dl-list">${active.map(row).join('')}</div>` : ''}
        ${done.length ? `<div class="section-head" style="margin-top:24px"><div class="section-title">${icon('clock')} 历史记录</div></div><div class="dl-list">${done.map(row).join('')}</div>` : ''}
        ${!xs.length ? `<div class="empty-state"><h3>还没有下载任务</h3><p>去频道选择视频，归档到你的服务器。</p><button onclick="go('channels')">浏览频道</button></div>` : ''}`;
    }
    await render();
    if (activePage === 'downloads') timer = setInterval(render, 1500);
  };

  /* ---------------- telegram login ---------------- */
  let pQrTimer = null;
  let pQrAccount = null;
  let pQrRun = 0;

  function pQrStop(cancel = false) {
    pQrRun++;
    clearInterval(pQrTimer);
    pQrTimer = null;
    if (cancel && pQrAccount !== null) api(`/telegram/qr/cancel?account_id=${pQrAccount}`, { method: 'POST' }).catch(() => {});
    pQrAccount = null;
  }

  window.telegramPage = async function () {
    pQrStop(false);
    const s = await telegramState();
    if (activePage !== 'telegram') return;
    const accountId = +$('#accountSelector').value;
    if (s.authorized) {
      content.innerHTML = `<div class="card connected-card">
        <div class="connected-avatar">${esc((s.name || 'T').slice(0, 1))}</div>
        <div class="connected-copy"><h3>${esc(s.name || 'Telegram 账号')}</h3><p>${esc(s.phone || '')} · 已连接，可浏览频道、下载与发送消息</p></div>
        <div class="connected-actions"><button onclick="go('channels')">${icon('tv')} 浏览频道</button><button class="ghost" onclick="go('accounts')">${icon('users')} 账号管理</button><button class="ghost-danger ghost" onclick="tgLogout()">结束会话</button></div>
      </div>
      <div class="card setting-card" style="max-width:720px"><h3>账号安全</h3><p>结束会话会撤销本应用在该账号上的登录，手机和其他设备不受影响。已下载视频、账号备注和本地媒体库都会保留。</p></div>`;
      return;
    }
    const apiConfigured = !!s.configured;
    content.innerHTML = `<div class="card telegram-login-card">
      <span class="eyebrow">CONNECT TELEGRAM</span>
      <h3 style="margin-top:6px">连接你的 Telegram</h3>
      <p class="muted" style="font-size:12.5px">推荐使用手机扫码，几秒即可完成。也可以使用手机号 + API 凭据登录。两步验证密码只用于当次验证，不会保存。</p>
      <div class="login-tabs"><button type="button" class="active" data-tab="qr">${icon('zap')} 扫码登录</button><button type="button" data-tab="api">${icon('shield')} 手机号 / API 登录</button></div>
      <div class="tab-pane" id="paneQr">
        ${apiConfigured ? `<p class="status" style="font-size:12px;color:#7fe3bd">当前账号已加密保存 API 凭据，可直接生成二维码。</p>` : `<p class="muted" style="font-size:12px">首次使用需要填写 Telegram 官方 API ID / API Hash。<a href="https://my.telegram.org/apps" target="_blank" rel="noreferrer" style="color:#9db0ff">前往申请</a></p>`}
        <div id="pApiFieldsQr" ${apiConfigured ? 'hidden' : ''}>
          <label>API ID<input id="pApiId" inputmode="numeric" placeholder="例如 12345678"></label>
          <label>API Hash<input id="pApiHash" type="password" placeholder="32 位十六进制字符"></label>
        </div>
        <div class="actions"><button type="button" id="pQrStart">${icon('zap')} 生成登录二维码</button><button type="button" class="ghost" id="pUseOwnApi" ${apiConfigured ? '' : 'hidden'}>使用其他 API 配置</button></div>
        <div class="qr-login-panel" id="pQrPanel" hidden>
          <img id="pQrImage" alt="Telegram 登录二维码" hidden>
          <p id="pQrStatus" role="status" aria-live="polite"></p>
          <ol class="steps"><li><b>1</b><span>打开手机 Telegram → 设置 → 设备 → 连接桌面设备</span></li><li><b>2</b><span>扫描二维码并在手机上确认登录</span></li><li><b>3</b><span>等待页面自动跳转到频道列表</span></li></ol>
          <button type="button" class="ghost" id="pQrCancel">取消扫码</button>
        </div>
      </div>
      <div class="tab-pane" id="paneApi" hidden>
        <div id="pApiFormWrap">
          ${apiConfigured ? `<p class="status" style="font-size:12px;color:#7fe3bd">将复用已保存的 API 凭据，只需输入手机号。</p>` : `<label>API ID<input id="pPhoneApiId" inputmode="numeric" placeholder="Telegram API ID"></label><label>API Hash<input id="pPhoneApiHash" type="password" placeholder="Telegram API Hash"></label>`}
          <label>手机号（含国家区号）<input id="pPhone" inputmode="tel" placeholder="例如 +8613800000000"></label>
          <div class="actions"><button type="button" id="pSendCode">${icon('chat')} 发送验证码</button></div>
        </div>
        <div class="error" id="pLoginError" role="alert"></div>
      </div>
    </div>`;

    const stop = () => pQrStop(true);
    document.querySelectorAll('.login-tabs button').forEach((button) => {
      button.onclick = () => {
        stop();
        document.querySelectorAll('.login-tabs button').forEach((x) => x.classList.toggle('active', x === button));
        $('#paneQr').hidden = button.dataset.tab !== 'qr';
        $('#paneApi').hidden = button.dataset.tab !== 'api';
      };
    });
    $('#pUseOwnApi').onclick = () => { $('#pApiFieldsQr').hidden = false; $('#pUseOwnApi').hidden = true; };
    $('#pQrCancel').onclick = () => { stop(); $('#pQrPanel').hidden = true; $('#pQrImage').removeAttribute('src'); $('#pQrStart').disabled = false; };
    $('#pQrStart').onclick = async () => {
      stop();
      const run = pQrRun;
      const fields = {};
      if (!$('#pApiFieldsQr').hidden) {
        fields.api_id = Number($('#pApiId').value) || null;
        fields.api_hash = ($('#pApiHash').value || '').trim() || null;
        if (!fields.api_id || !fields.api_hash) return toast('请填写 Telegram API ID 和 API Hash');
      }
      $('#pQrStart').disabled = true;
      $('#pQrPanel').hidden = false;
      $('#pQrStatus').textContent = '正在安全生成二维码…';
      pQrAccount = accountId;
      try {
        const state = await api(`/telegram/qr/start?account_id=${accountId}`, { method: 'POST', body: JSON.stringify(fields) }, 60000);
        if (run !== pQrRun || activePage !== 'telegram') {
          api(`/telegram/qr/cancel?account_id=${accountId}`, { method: 'POST' }).catch(() => {});
          return;
        }
        pRenderQr(state, accountId, run);
      } catch (e) {
        if (run !== pQrRun || activePage !== 'telegram') return;
        $('#pQrStatus').textContent = e.message;
        $('#pQrStart').disabled = false;
      }
    };

    function pRenderQr(state, account, run) {
      if (run !== pQrRun || activePage !== 'telegram') return;
      if (state.state === 'authorized') {
        pQrStop(false); toast('Telegram 扫码登录成功'); loadAccounts().catch(() => {}); go('channels');
        return;
      }
      if (state.state === 'password_needed') {
        pQrStop(false);
        pShow2FA(account);
        return;
      }
      const image = $('#pQrImage');
      const status = $('#pQrStatus');
      if (state.state === 'waiting') {
        if (state.image) { image.src = state.image; image.hidden = false; }
        status.textContent = '等待手机扫描并确认，二维码过期会自动刷新。';
        clearInterval(pQrTimer);
        pQrTimer = setInterval(async () => {
          try {
            const next = await api(`/telegram/qr/status?account_id=${account}`);
            pRenderQr(next, account, run);
          } catch (e) {
            if (run !== pQrRun || activePage !== 'telegram') return;
            clearInterval(pQrTimer);
            status.textContent = e.message;
            $('#pQrStart').disabled = false;
          }
        }, 1600);
      } else {
        clearInterval(pQrTimer);
        image.hidden = true; image.removeAttribute('src');
        status.textContent = state.message || '等待已结束，请重新生成二维码。';
        $('#pQrStart').disabled = false;
      }
    }

    function pShow2FA(account) {
      $('#pQrPanel').hidden = true;
      content.innerHTML = `<div class="card telegram-login-card"><span class="eyebrow">TWO-STEP VERIFICATION</span><h3 style="margin-top:6px">输入两步验证密码</h3><p class="muted" style="font-size:12.5px">该密码只发送给 Telegram 完成本次验证，不会写入数据库或日志。</p><label>两步验证密码<input id="p2fa" type="password" autocomplete="current-password" required></label><div class="actions"><button id="p2faSubmit">完成登录</button><button class="ghost" onclick="go('telegram')">返回</button></div><div class="error" id="p2faError"></div></div>`;
      $('#p2faSubmit').onclick = async () => {
        const error = $('#p2faError');
        error.textContent = '';
        try {
          await api(`/telegram/verify-password?account_id=${account}`, { method: 'POST', body: JSON.stringify({ password: $('#p2fa').value }) });
          toast('Telegram 登录成功');
          await loadAccounts();
          go('channels');
        } catch (e) { error.textContent = e.message; }
      };
      $('#p2fa').focus();
    }

    $('#pSendCode').onclick = async () => {
      const error = $('#pLoginError');
      error.textContent = '';
      const payload = { phone: ($('#pPhone').value || '').trim() };
      if (!payload.phone) { error.textContent = '请输入手机号'; return; }
      if ($('#pPhoneApiId')) {
        payload.api_id = Number($('#pPhoneApiId').value) || null;
        payload.api_hash = ($('#pPhoneApiHash').value || '').trim() || null;
        if (!payload.api_id || !payload.api_hash) { error.textContent = '请填写 API ID 和 API Hash'; return; }
      }
      $('#pSendCode').disabled = true;
      error.textContent = '正在请求 Telegram 发送验证码…';
      try {
        await api(`/telegram/send-code?account_id=${accountId}`, { method: 'POST', body: JSON.stringify(payload) }, 60000);
        $('#pApiFormWrap').innerHTML = `<p class="status" style="font-size:12.5px;color:#7fe3bd">验证码已发送到你的 Telegram 官方消息，请在下方输入。</p><label>验证码<input id="pCode" inputmode="numeric" autocomplete="one-time-code" placeholder="例如 12345"></label><div class="actions"><button id="pVerifyCode">${icon('check')} 验证并登录</button><button class="ghost" onclick="go('telegram')">返回</button></div>`;
        $('#pCode').focus();
        $('#pVerifyCode').onclick = async () => {
          error.textContent = '';
          try {
            const result = await api(`/telegram/verify-code?account_id=${accountId}`, { method: 'POST', body: JSON.stringify({ code: $('#pCode').value.trim() }) });
            if (result.result === 'password_needed') { pShow2FA(accountId); return; }
            toast('Telegram 登录成功');
            await loadAccounts();
            go('channels');
          } catch (e) { error.textContent = e.message; }
        };
      } catch (e) {
        error.textContent = e.message;
        $('#pSendCode').disabled = false;
      }
    };
  };

  /* stop QR polling when leaving the page or switching accounts */
  document.addEventListener('click', (e) => { if (e.target.closest('[data-page]')) pQrStop(true); }, true);
  document.addEventListener('change', (e) => { if (e.target.id === 'accountSelector') pQrStop(true); }, true);

  /* ---------------- accounts ---------------- */
  window.accountsPage = async function () {
    const rows = await loadAccounts();
    if (activePage !== 'accounts') return;
    content.innerHTML = `<div class="account-page">
      <div class="account-page-heading"><div><h3>Telegram 账号</h3><p class="muted">独立登录 · 加密备份 · 跨服务器迁移</p></div><div class="account-tools"><button class="ghost" onclick="openAccountBackup()">${icon('download')} 导出备份</button><button class="ghost" onclick="openAccountRestore()">${icon('refresh')} 导入账号</button><button id="addAccountButton" onclick="addAccount()">${icon('plus')} 添加账号</button></div></div>
      <div class="account-list">${rows.map((a) => `<article class="card account-card ${a.active ? 'is-current' : ''}" data-account-id="${a.id}">
        <div class="account-avatar">${esc((a.label || '?').trim().slice(0, 1))}</div>
        <div class="account-details"><h3>${esc(a.label)} ${a.active ? '<span class="current-account-badge">当前账号</span>' : ''}</h3><p>${esc(a.name || '')}${a.phone ? ' · ' + esc(a.phone) : ''}</p><span class="account-state ${a.authorized ? 'connected' : ''}">${a.restore_pending ? '已恢复 · 切换后连接' : a.status === 'unavailable' ? '状态暂不可用，请刷新' : a.authorized ? '● 已登录' : '○ 未登录'}</span></div>
        <div class="account-card-actions">
          ${a.active ? '' : `<button class="ghost" onclick="switchAccount(${a.id})">切换账号</button>`}
          ${!a.authorized && !a.restore_pending ? `<button onclick="pAccountLogin(${a.id})">${icon('zap')} 扫码 / API 登录</button>` : ''}
          <button class="ghost" data-action="rename" onclick="renameAccount(${a.id})">重命名</button>
          <button class="ghost" data-action="backup" onclick="openAccountBackup(${a.id})">导出账号</button>
          ${a.authorized !== false || a.session_exists ? `<button class="ghost ghost-danger" data-action="logout" onclick="endAccountSession(${a.id})">结束会话</button>` : ''}
          ${rows.length > 1 ? `<button class="ghost" data-action="remove" onclick="removeAccount(${a.id})">移除账号</button>` : ''}
        </div>
      </article>`).join('')}</div>
      <div class="card account-help"><h3>账号与会话</h3><p>切换账号会保留登录；结束会话会撤销本应用在 Telegram 的登录，下次使用需重新扫码或验证码登录。手机和其他设备的登录保持有效。</p><p class="muted">每个账号的 Session、消息和下载来源独立保存。已下载视频保留在本地媒体库；退出后台仅退出网页管理端。</p><button class="ghost" onclick="go('accounts')">${icon('refresh')} 刷新登录状态</button></div>
    </div>`;
  };

  window.pAccountLogin = async function (id) {
    try {
      await changeAccount(id);
      await go('telegram');
    } catch (e) { toast(e.message); }
  };

  /* ---------------- settings ---------------- */
  window.settings = async function () {
    const [s, d, accounts, security] = await Promise.all([telegramState(), api('/dashboard'), api('/accounts'), api('/settings/security')]);
    if (activePage !== 'settings') return;
    credentialUsesSeparatePassword = security.has_view_password;
    content.innerHTML = `
      <div class="grid" style="margin-top:0">
        <div class="card setting-card"><div class="section-title">外观与备份</div><p class="muted" style="margin-top:8px">明暗主题在此设备自动记住。账号备份可迁移到另一台部署，恢复时保留原有账号。</p><div class="actions"><button class="ghost" onclick="toggleTheme()">切换明暗主题</button><button class="ghost" onclick="openAccountBackup()">导出账号</button><button class="ghost" onclick="openAccountRestore()">导入备份</button></div></div>
        <div class="card setting-card"><div class="section-title">${icon('users')} 当前 Telegram 账号</div><p style="margin-top:8px">${s.authorized ? '已登录：' + esc(s.name || '') + (s.phone ? '（' + esc(s.phone) + '）' : '') : '尚未登录'}</p><div class="actions">${s.authorized ? '<button class="ghost-danger ghost" onclick="tgLogout()">结束当前会话</button>' : '<button onclick="go(\'telegram\')">去登录 Telegram</button>'}<button class="ghost" onclick="go('accounts')">管理 ${accounts.length} 个账号</button></div></div>
        <div class="card setting-card"><div class="section-title">${icon('cloud')} 运行状态</div><p style="margin-top:8px">Web 服务正常 · 数据盘正常 · 下载 worker 2 个<br><span class="muted">数据目录 /data/telegram-video-manager<br>剩余空间 ${fmt(d.disk.free)}</span></p></div>
      </div>
      <div class="card setting-card security-card"><div><div class="section-title">${icon('shield')} 密码与安全</div><p class="muted" style="margin-top:6px">管理员密码用于登录后台；查看密码只用于显示 API ID/API Hash。修改管理员密码后所有旧登录会立即失效。</p></div><div class="password-actions"><button onclick="changeAdminPassword()">修改管理员密码</button><button class="ghost" onclick="changeViewPassword()">${security.has_view_password ? '修改查看密码' : '设置独立查看密码'}</button>${security.has_view_password ? '<button class="ghost" onclick="resetViewPassword()">恢复使用管理员密码查看</button>' : ''}</div><span class="status">查看凭据：${security.has_view_password ? '使用独立查看密码' : '使用管理员密码'}</span></div>
      <div class="card setting-card credential-card"><div class="grow"><div class="section-title">${icon('key')} Telegram API 凭据</div><p class="muted">${s.configured ? '当前账号已加密保存 API ID 和 API Hash。查看时需要输入' + (security.has_view_password ? '独立查看密码' : '管理员密码') + '。' : '当前账号尚未配置 API 凭据，可在 Telegram 登录页填写。'}</p></div>${s.configured ? '<button onclick="revealTelegramCredentials()">查看 / 复制</button>' : '<button onclick="go(\'telegram\')">去配置</button>'}</div>
      <div class="card setting-card"><div class="section-title">${icon('zap')} 原画与拖动预览</div><p style="margin-top:8px">默认原画，同一播放器同步播放声音与画面。后台生成原编码分片和画面切片，拖动时即时预览；停留或松手后加载目标原画。也可手动生成并切换流畅版。</p><div class="actions"><button class="ghost" onclick="go('library')">打开媒体库</button></div></div>
      <div class="card setting-card"><div class="section-title">${icon('download')} 存储维护</div><p style="margin-top:8px">只清理本项目临时下载目录，不会触碰正式视频和服务器其他文件。</p><div class="actions"><button class="ghost-danger ghost" onclick="cleanupTemp()">清理临时文件</button><button class="ghost" onclick="go('downloads')">查看下载任务</button></div></div>`;
  };

  /* ---------------- nav helpers ---------------- */
  function pCloseNav() {
    document.querySelector('aside')?.classList.remove('open');
    $('#navBackdrop')?.classList.remove('show');
    $('#menu')?.setAttribute('aria-expanded', 'false');
  }
  const menu = document.getElementById('menu');
  if (menu) {
    menu.onclick = () => {
      const open = document.querySelector('aside').classList.toggle('open');
      $('#navBackdrop').classList.toggle('show', open);
      menu.setAttribute('aria-expanded', String(open));
    };
  }
  const backdrop = document.getElementById('navBackdrop');
  if (backdrop) backdrop.addEventListener('click', pCloseNav);
  document.addEventListener('click', (e) => { if (e.target.closest('[data-page]')) pCloseNav(); }, true);

  /* expose for inline handlers */
  window.pQrStop = pQrStop;
})();
