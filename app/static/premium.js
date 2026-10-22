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
  const thumbUrl = (x) => (x.thumb_path ? `/api/media/${x.id}/thumbnail` : '');
  const smoothReady = (x) => x && x.smooth_status === 'ready' && x.smooth_path;
  const smoothBusy = (x) => x && (x.smooth_status === 'queued' || x.smooth_status === 'processing');

  function mediaCard(x, opts = {}) {
    const ready = smoothReady(x);
    const busy = smoothBusy(x);
    const progress = Math.round(Number(x.smooth_progress) || 0);
    const flags = [];
    if (x.width && x.height) flags.push(`<span class="flag">${x.width}×${x.height}</span>`);
    if (ready) flags.push('<span class="flag quality">480P 流畅</span>');
    else if (busy) flags.push(`<span class="flag optimizing">优化 ${progress}%</span>`);
    const selected = selectedMedia.has(Number(x.id));
    return `<article class="card media-card-v2" data-media-id="${x.id}">
      <div class="media-poster">
        <div class="poster-fallback">${icon('film')}</div>
        ${x.thumb_path ? `<img loading="lazy" src="${thumbUrl(x)}" alt="" onerror="this.remove()">` : ''}
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
        <div class="media-name" title="${esc(x.file_name)}">${esc(x.file_name)}</div>
        <div class="media-sub">
          <span>${esc(x.channel_title || '未知来源')}</span><span class="dot"></span>
          <span>${fmt(x.size)}</span><span class="dot"></span>
          <span>${x.size && x.duration ? ((x.size * 8 / x.duration / 1e6).toFixed(2) + ' Mbps') : duration(x.duration)}</span>
        </div>
        <div class="media-actions">
          <button type="button" onclick="play(${x.id})">${icon('play')} 播放</button>
          <button type="button" class="icon-action" onclick="pDownload(${x.id})" title="下载原画">${icon('download')}</button>
          <button type="button" class="icon-action" onclick="pMediaMenu(${x.id})" title="更多操作">${icon('chevron')}</button>
        </div>
      </div>
    </article>`;
  }

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
    selectedMedia.clear();
    content.innerHTML = `
      <div class="toolbar">
        <input id="mediaSearch" placeholder="搜索视频名称或频道" onkeydown="if(event.key==='Enter')loadMedia()">
        <select id="mediaSort" onchange="loadMedia()">
          <option value="time">最新归档</option><option value="name">按名称</option><option value="size">按大小</option>
        </select>
        <button class="ghost p-toolbar-search" onclick="loadMedia()">${icon('search')} 搜索</button>
        <label><input id="selectAllMedia" type="checkbox" onchange="toggleAllMedia(this.checked)"> 全选</label>
        <button id="batchDownloadBtn" class="ghost" onclick="pDownloadSelected()" disabled>${icon('download')} 批量下载 (<span>0</span>)</button>
        <button id="deleteSelectedBtn" class="danger" onclick="deleteSelectedMedia()" disabled>${icon('x')} 删除选中 (<span>0</span>)</button>
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
    const ids = new Set(xs.map((x) => Number(x.id)));
    [...selectedMedia].forEach((id) => { if (!ids.has(id)) selectedMedia.delete(id); });
    box.innerHTML = xs.length
      ? xs.map((x) => mediaCard(x)).join('')
      : `<div class="empty-state" style="grid-column:1/-1"><h3>没有找到视频</h3><p>尝试换一个关键词，或先去频道下载视频。</p><button onclick="go('channels')">浏览频道</button></div>`;
    updateMediaSelection();
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
    toast('已开始下载到本机');
  };

  window.pMediaMenu = async function (id) {
    const x = await api('/media/' + id);
    const ready = smoothReady(x);
    const busy = smoothBusy(x);
    modal(`<h3 style="margin-bottom:4px">${esc(x.file_name)}</h3>
      <p class="muted" style="font-size:12px">${esc(x.channel_title)} · ${fmt(x.size)} · ${x.width}×${x.height} · ${duration(x.duration)}</p>
      <div class="actions" style="display:grid;grid-template-columns:1fr 1fr;gap:9px;margin-top:18px">
        <button onclick="closeModal();play(${id})">${icon('play')} 原画播放</button>
        <button class="ghost" onclick="pDownload(${id})">${icon('download')} 下载原画</button>
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
  let pResumeToast = false;

  window.play = async function (id, preferred) {
    const x = await api('/media/' + id);
    let smooth = smoothReady(x);
    const autoSmooth = !preferred && smooth && /(^|-)2g$|3g|slow-2g/.test(navigator.connection?.effectiveType || '') ;
    let quality = preferred === 'smooth' && smooth ? 'smooth' : 'original';
    if (autoSmooth) quality = 'smooth';
    const src = `/api/media/${id}/stream?quality=${quality}`;
    modal(`<div class="video-modal player-shell">
      <div class="player-top">
        <div class="player-title"><h3>${esc(x.file_name)}</h3><p>${esc(x.channel_title)} · ${x.width}×${x.height} · ${fmt(x.size)}</p></div>
        <button class="quality-btn" id="qualityButton" type="button" ${smooth ? '' : 'disabled'} title="切换原画 / 流畅 480P">${quality === 'smooth' ? '480P 流畅' : '原画'}</button>
        <button class="ctl" id="playerClose" type="button" aria-label="关闭">${icon('x')}</button>
      </div>
      <div class="player-stage" id="playerStage">
        ${x.thumb_path ? `<div class="player-ambient" style="background-image:url('${thumbUrl(x)}')"></div>` : ''}
        <video id="player" playsinline webkit-playsinline preload="auto" poster="${x.thumb_path ? thumbUrl(x) : ''}"></video>
        <div class="player-spinner show" id="playerSpinner"></div>
        <button class="player-bigplay" id="bigPlay" type="button" aria-label="播放">${icon('play')}</button>
        <div class="buffer-status" id="bufferStatus" hidden>正在缓冲…</div>
      </div>
      <div class="player-controls">
        <div class="seek-wrap" id="seekWrap">
          <div class="seek-track"><div class="seek-buffer" id="seekBuffer"></div><div class="seek-played" id="seekPlayed"></div></div>
          <div class="seek-thumb" id="seekThumb"></div>
          <input class="seek-input" id="seekInput" type="range" min="0" max="1000" value="0" step="1" aria-label="播放进度">
        </div>
        <div class="controls-row">
          <button class="ctl" id="playToggle" type="button" aria-label="播放/暂停">${icon('play')}</button>
          <span class="time" id="timeLabel">0:00 / ${duration(x.duration)}</span>
          <span class="ctl-spacer"></span>
          <div class="volume-wrap" id="volumeWrap"><input id="volumeInput" type="range" min="0" max="1" step="0.05" value="1" aria-label="音量"></div>
          <button class="ctl" id="muteToggle" type="button" aria-label="静音">${icon('volume')}</button>
          <button class="ctl" id="speedButton" type="button" title="播放速度" style="width:auto;padding:0 8px;font-size:11px">1×</button>
          <button class="ctl" id="pipButton" type="button" aria-label="画中画">${icon('pip')}</button>
          <a class="ctl" id="downloadButton" href="/api/media/${id}/stream?download=true" title="下载原画" aria-label="下载">${icon('download')}</a>
          <button class="ctl" id="fullscreenButton" type="button" aria-label="全屏">${icon('expand')}</button>
        </div>
      </div>
      <div class="player-foot">
        <div class="player-meta"><span>画质 <b id="metaQuality">${quality === 'smooth' ? '480P 流畅' : '原画 · 未转码'}</b></span><span>码率 <b id="metaBitrate">${x.size && x.duration ? (x.size * 8 / x.duration / 1e6).toFixed(2) + ' Mbps' : '未知'}</b></span><span>时长 <b>${duration(x.duration)}</b></span><span class="player-hint">空格 播放 · ← → 快进 · F 全屏</span></div>
        <div class="player-actions"><button class="ghost" id="smoothButton" type="button">${smooth ? '播放 480P 流畅版' : '生成 480P 流畅版'}</button><a href="/api/media/${id}/stream?download=true">${icon('download')}<span>下载到本机</span></a></div>
      </div>
      <div class="player-error" id="playerError" hidden></div>
    </div>`, true);
    const video = $('#player');
    const stage = $('#playerStage');
    const spinner = $('#playerSpinner');
    const bigPlay = $('#bigPlay');
    const buffer = $('#bufferStatus');
    const playToggle = $('#playToggle');
    const seek = $('#seekInput');
    const played = $('#seekPlayed');
    const buffered = $('#seekBuffer');
    const thumb = $('#seekThumb');
    const timeLabel = $('#timeLabel');
    const qualityButton = $('#qualityButton');
    const smoothButton = $('#smoothButton');
    const downloadButton = $('#downloadButton');
    let saveAt = 0;
    let waitingCount = 0;
    let dragging = false;
    let closed = false;

    const setQualityLink = (q) => {
      downloadButton.href = `/api/media/${id}/stream?download=true${q === 'smooth' ? '&quality=smooth' : ''}`;
      playToggle.title = '';
    };

    const paint = () => {
      const d = Number(video.duration) || Number(x.duration) || 0;
      const current = Number(video.currentTime) || 0;
      if (d > 0) {
        const p = pct(current, d);
        played.style.width = `${p}%`;
        thumb.style.left = `${p}%`;
        if (!dragging) seek.value = String(Math.round(p * 10));
        timeLabel.textContent = `${duration(current)} / ${duration(d)}`;
        let end = 0;
        try {
          for (let i = 0; i < video.buffered.length; i++) {
            if (video.buffered.start(i) <= current + 0.5 && video.buffered.end(i) >= current) {
              end = video.buffered.end(i);
              break;
            }
            end = Math.max(end, video.buffered.end(i));
          }
        } catch {}
        buffered.style.width = `${pct(end, d)}%`;
      }
    };

    const showSpinner = (on) => spinner.classList.toggle('show', on);
    const hideBig = () => bigPlay.classList.add('hide');
    const showBig = () => bigPlay.classList.remove('hide');

    video.src = src;
    setQualityLink(quality);
    video.load();
    video.play().catch(() => {});

    const saved = Number(localStorage.getItem('tvm-pos-' + id) || 0);
    video.addEventListener('loadedmetadata', () => {
      const d = Number(video.duration) || 0;
      if (saved > 5 && d > 0 && saved < d - 12) {
        video.currentTime = saved;
        if (!pResumeToast) {
          pResumeToast = true;
          toast(`已从上次位置 ${duration(saved)} 继续播放`);
          setTimeout(() => { pResumeToast = false; }, 4000);
        }
      }
      paint();
    });
    video.addEventListener('timeupdate', () => {
      paint();
      const now = Date.now();
      if (now - saveAt > 4000 && video.currentTime > 5) {
        saveAt = now;
        try { localStorage.setItem('tvm-pos-' + id, String(Math.floor(video.currentTime))); } catch {}
      }
    });
    video.addEventListener('progress', paint);
    video.addEventListener('waiting', () => {
      waitingCount++;
      showSpinner(true); buffer.hidden = false;
      if (waitingCount >= 2 && quality === 'original' && smooth && !video.paused) {
        toast('网络较慢，已自动切换到 480P 流畅版');
        pSetQuality('smooth');
      }
    });
    video.addEventListener('playing', () => { showSpinner(false); buffer.hidden = true; hideBig(); waitingCount = 0; playToggle.innerHTML = icon('pause'); });
    video.addEventListener('canplay', () => { showSpinner(false); buffer.hidden = true; });
    video.addEventListener('pause', () => { showBig(); playToggle.innerHTML = icon('play'); });
    video.addEventListener('ended', () => { showBig(); playToggle.innerHTML = icon('play'); });
    video.addEventListener('error', async () => {
      if (closed) return;
      showSpinner(false);
      if (quality === 'original' && smooth) {
        toast('原画编码或网络异常，已切换流畅版');
        pSetQuality('smooth');
        return;
      }
      $('#playerError').hidden = false;
      $('#playerError').textContent = '这个视频的编码可能不被当前浏览器支持。可以下载原文件后用本地播放器播放。';
    });
    video.addEventListener('volumechange', () => { $('#muteToggle').style.opacity = video.muted || video.volume === 0 ? '.5' : '1'; });

    const toggle = () => { if (video.paused) video.play().catch(() => {}); else video.pause(); };
    playToggle.onclick = toggle;
    bigPlay.onclick = toggle;
    video.addEventListener('click', toggle);

    seek.addEventListener('pointerdown', () => { dragging = true; });
    seek.addEventListener('pointerup', () => { dragging = false; });
    seek.addEventListener('input', () => {
      const d = Number(video.duration) || 0;
      if (!d) return;
      const value = Number(seek.value) / 1000 * d;
      played.style.width = `${Number(seek.value) / 10}%`;
      thumb.style.left = `${Number(seek.value) / 10}%`;
      timeLabel.textContent = `${duration(value)} / ${duration(d)}`;
    });
    seek.addEventListener('change', () => {
      const d = Number(video.duration) || 0;
      if (d) { video.currentTime = Number(seek.value) / 1000 * d; video.play().catch(() => {}); }
    });
    $('#muteToggle').onclick = () => { video.muted = !video.muted; };
    $('#volumeInput').oninput = (e) => { video.volume = Number(e.target.value); video.muted = false; };
    $('#volumeWrap').onclick = (e) => e.stopPropagation();
    $('#muteToggle').onmouseenter = () => $('#volumeWrap').classList.add('open');
    $('#volumeWrap').onmouseleave = () => $('#volumeWrap').classList.remove('open');

    let speed = 1;
    const rates = [1, 1.25, 1.5, 2, 0.75];
    $('#speedButton').onclick = () => {
      speed = rates[(rates.indexOf(speed) + 1) % rates.length];
      video.playbackRate = speed;
      $('#speedButton').textContent = speed + '×';
    };
    $('#pipButton').onclick = async () => {
      try {
        if (document.pictureInPictureElement) await document.exitPictureInPicture();
        else await video.requestPictureInPicture();
      } catch { toast('当前浏览器不支持画中画'); }
    };
    $('#fullscreenButton').onclick = async () => {
      try {
        if (document.fullscreenElement) await document.exitFullscreen();
        else await (stage.requestFullscreen ? stage.requestFullscreen() : video.webkitEnterFullscreen?.());
      } catch { toast('当前浏览器不支持全屏'); }
    };

    const pSetQuality = async (next) => {
      if (next === quality) return;
      if (next === 'smooth' && !smooth) return;
      const at = Number(video.currentTime) || 0;
      const paused = video.paused;
      quality = next;
      video.src = `/api/media/${id}/stream?quality=${quality}`;
      setQualityLink(quality);
      showSpinner(true);
      video.load();
      const restore = () => {
        video.currentTime = at;
        video.removeEventListener('loadedmetadata', restore);
        if (!paused) video.play().catch(() => {});
      };
      video.addEventListener('loadedmetadata', restore);
      qualityButton.textContent = quality === 'smooth' ? '480P 流畅' : '原画';
      const metaQuality = $('#metaQuality');
      const metaBitrate = $('#metaBitrate');
      if (metaQuality) metaQuality.textContent = quality === 'smooth' ? '480P 流畅' : '原画 · 未转码';
      if (metaBitrate) {
        const size = quality === 'smooth' ? Number(x.smooth_size) : Number(x.size);
        metaBitrate.textContent = size && x.duration ? (size * 8 / x.duration / 1e6).toFixed(2) + ' Mbps' : '未知';
      }
      toast(quality === 'smooth' ? '已切换到 480P 流畅版' : '已切换到原画');
    };
    window.pSetQuality = pSetQuality;

    qualityButton.onclick = () => {
      if (smooth || smoothReady(x)) pSetQuality(quality === 'smooth' ? 'original' : 'smooth');
    };
    smoothButton.onclick = async () => {
      if (smooth || smoothReady(x)) { pSetQuality('smooth'); return; }
      smoothButton.disabled = true;
      smoothButton.textContent = '正在生成…';
      try {
        await api(`/media/${id}/smooth`, { method: 'POST' });
        const timer = setInterval(async () => {
          try {
            const state = await api(`/media/${id}/smooth`);
            smoothButton.textContent = state.ready ? '播放 480P 流畅版' : `生成中 ${Math.round(state.progress)}%`;
            if (state.ready) {
              clearInterval(timer);
              smooth = true;
              x.smooth_status = 'ready';
              x.smooth_path = 'ready';
              smoothButton.disabled = false;
              smoothButton.onclick = () => pSetQuality('smooth');
              qualityButton.disabled = false;
              toast('480P 流畅版已生成');
            } else if (state.status === 'failed') {
              clearInterval(timer);
              smoothButton.disabled = false;
              smoothButton.textContent = '重新生成 480P';
              toast(state.error || '流畅版生成失败');
            }
          } catch { clearInterval(timer); smoothButton.disabled = false; }
        }, 2000);
      } catch (e) {
        toast(e.message);
        smoothButton.disabled = false;
        smoothButton.textContent = '生成 480P 流畅版';
      }
    };

    const onBackdrop = (e) => { if (e.target.id === 'modal') close(); };
    const close = () => {
      if (closed) return;
      closed = true;
      try { localStorage.setItem('tvm-pos-' + id, String(Math.floor(video.currentTime || 0))); } catch {}
      video.pause(); video.removeAttribute('src'); video.load();
      $('#modal').removeEventListener('click', onBackdrop);
      closeModal();
    };
    $('#playerClose').onclick = close;
    $('#modal').addEventListener('click', onBackdrop);

    if (x.smooth_status === 'failed' && !smooth) {
      $('#playerError').hidden = false;
      $('#playerError').textContent = '流畅版生成失败：' + (x.smooth_error || '编码不受支持');
    }

    const keyHandler = (e) => {
      if (!document.getElementById('player')) { document.removeEventListener('keydown', keyHandler); return; }
      if (e.target.matches('input,textarea,select')) return;
      if (e.code === 'Space') { e.preventDefault(); toggle(); }
      else if (e.code === 'ArrowLeft') { e.preventDefault(); video.currentTime = Math.max(0, video.currentTime - 5); }
      else if (e.code === 'ArrowRight') { e.preventDefault(); video.currentTime = Math.min(video.duration || 0, video.currentTime + 5); }
      else if (e.code === 'ArrowUp') { e.preventDefault(); video.volume = Math.min(1, video.volume + 0.1); }
      else if (e.code === 'ArrowDown') { e.preventDefault(); video.volume = Math.max(0, video.volume - 0.1); }
      else if (e.key === 'f' || e.key === 'F') { $('#fullscreenButton').click(); }
      else if (e.key === 'm' || e.key === 'M') { video.muted = !video.muted; }
      else if (e.key === 'Escape') { close(); }
    };
    document.addEventListener('keydown', keyHandler);
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
      content.innerHTML = `<div class="notice"><b>双并发 · 断点续传</b><span>暂停、断网或服务重启都会保留临时文件；点击“继续”从现有进度恢复，不重复下载。</span></div>
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

  function pQrStop(cancel = false) {
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
      const fields = {};
      if (!$('#pApiFieldsQr').hidden) {
        fields.api_id = Number($('#pApiId').value) || null;
        fields.api_hash = ($('#pApiHash').value || '').trim() || null;
        if (!fields.api_id || !fields.api_hash) return toast('请填写 Telegram API ID 和 API Hash');
      }
      $('#pQrStart').disabled = true;
      $('#pQrPanel').hidden = false;
      $('#pQrStatus').textContent = '正在安全生成二维码…';
      try {
        const state = await api(`/telegram/qr/start?account_id=${accountId}`, { method: 'POST', body: JSON.stringify(fields) }, 60000);
        if (activePage !== 'telegram') return;
        pQrAccount = accountId;
        pRenderQr(state, accountId);
      } catch (e) {
        $('#pQrStatus').textContent = e.message;
        $('#pQrStart').disabled = false;
      }
    };

    function pRenderQr(state, account) {
      if (activePage !== 'telegram') return;
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
            pRenderQr(next, account);
          } catch (e) {
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
      <div class="account-page-heading"><div><h3>Telegram 账号</h3><p class="muted">每个账号使用独立 Session，可分别扫码或 API 登录，随时切换。</p></div><button onclick="addAccount()">${icon('plus')} 添加账号</button></div>
      <div class="account-list">${rows.map((a) => `<article class="card account-card ${a.active ? 'is-current' : ''}">
        <div class="account-avatar">${esc((a.label || '?').trim().slice(0, 1))}</div>
        <div class="account-details"><h3>${esc(a.label)} ${a.active ? '<span class="current-account-badge">当前账号</span>' : ''}</h3><p>${esc(a.name || '')}${a.phone ? ' · ' + esc(a.phone) : ''}</p><span class="account-state ${a.authorized ? 'connected' : ''}">${a.status === 'unavailable' ? '状态暂不可用，请刷新' : a.authorized ? '● 已登录' : '○ 未登录'}</span></div>
        <div class="account-card-actions">
          ${a.active ? '' : `<button class="ghost" onclick="switchAccount(${a.id})">切换账号</button>`}
          ${!a.authorized ? `<button onclick="pAccountLogin(${a.id})">${icon('zap')} 扫码 / API 登录</button>` : ''}
          <button class="ghost" onclick="renameAccount(${a.id})">重命名</button>
          ${a.authorized !== false || a.session_exists ? `<button class="ghost ghost-danger" onclick="endAccountSession(${a.id})">结束会话</button>` : ''}
          ${rows.length > 1 ? `<button class="ghost" onclick="removeAccount(${a.id})">移除账号</button>` : ''}
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
        <div class="card setting-card"><div class="section-title">${icon('users')} 当前 Telegram 账号</div><p style="margin-top:8px">${s.authorized ? '已登录：' + esc(s.name || '') + (s.phone ? '（' + esc(s.phone) + '）' : '') : '尚未登录'}</p><div class="actions">${s.authorized ? '<button class="ghost-danger ghost" onclick="tgLogout()">结束当前会话</button>' : '<button onclick="go(\'telegram\')">去登录 Telegram</button>'}<button class="ghost" onclick="go('accounts')">管理 ${accounts.length} 个账号</button></div></div>
        <div class="card setting-card"><div class="section-title">${icon('cloud')} 运行状态</div><p style="margin-top:8px">Web 服务正常 · 数据盘正常 · 下载 worker 2 个<br><span class="muted">数据目录 /data/telegram-video-manager<br>剩余空间 ${fmt(d.disk.free)}</span></p></div>
      </div>
      <div class="card setting-card security-card"><div><div class="section-title">${icon('shield')} 密码与安全</div><p class="muted" style="margin-top:6px">管理员密码用于登录后台；查看密码只用于显示 API ID/API Hash。修改管理员密码后所有旧登录会立即失效。</p></div><div class="password-actions"><button onclick="changeAdminPassword()">修改管理员密码</button><button class="ghost" onclick="changeViewPassword()">${security.has_view_password ? '修改查看密码' : '设置独立查看密码'}</button>${security.has_view_password ? '<button class="ghost" onclick="resetViewPassword()">恢复使用管理员密码查看</button>' : ''}</div><span class="status">查看凭据：${security.has_view_password ? '使用独立查看密码' : '使用管理员密码'}</span></div>
      <div class="card setting-card credential-card"><div class="grow"><div class="section-title">${icon('key')} Telegram API 凭据</div><p class="muted">${s.configured ? '当前账号已加密保存 API ID 和 API Hash。查看时需要输入' + (security.has_view_password ? '独立查看密码' : '管理员密码') + '。' : '当前账号尚未配置 API 凭据，可在 Telegram 登录页填写。'}</p></div>${s.configured ? '<button onclick="revealTelegramCredentials()">查看 / 复制</button>' : '<button onclick="go(\'telegram\')">去配置</button>'}</div>
      <div class="card setting-card"><div class="section-title">${icon('zap')} 播放与转码</div><p style="margin-top:8px">新下载的 MP4 会自动把索引移动到文件头（faststart），拖动进度更快。流畅 480P 在后台生成，生成完成后可在播放器一键切换。</p><div class="actions"><button class="ghost" onclick="go('library')">打开媒体库查看优化状态</button></div></div>
      <div class="card setting-card"><div class="section-title">${icon('download')} 存储维护</div><p style="margin-top:8px">只清理本项目临时下载目录，不会触碰正式视频和服务器其他文件。</p><div class="actions"><button class="ghost-danger ghost" onclick="cleanupTemp()">清理临时文件</button><button class="ghost" onclick="go('downloads')">查看下载任务</button></div></div>`;
  };

  /* ---------------- nav helpers ---------------- */
  function pCloseNav() {
    document.querySelector('aside')?.classList.remove('open');
    $('#navBackdrop')?.classList.remove('show');
  }
  const menu = document.getElementById('menu');
  if (menu) {
    menu.addEventListener('click', () => {
      const open = document.querySelector('aside').classList.toggle('open');
      $('#navBackdrop').classList.toggle('show', open);
    });
  }
  const backdrop = document.getElementById('navBackdrop');
  if (backdrop) backdrop.addEventListener('click', pCloseNav);
  document.addEventListener('click', (e) => { if (e.target.closest('[data-page]')) pCloseNav(); }, true);

  /* expose for inline handlers */
  window.pQrStop = pQrStop;
})();
