/* Account-scoped catalogue: covers, live task badges, filters and append-only pages. */
(function () {
  'use strict';
  let view = null, run = 0;
  let channelRequest = 0;
  const times = n => `${Math.floor((n || 0) / 60)}:${String(Math.floor((n || 0) % 60)).padStart(2, '0')}`;
  const labels = { queued:'排队中', downloading:'下载中', pausing:'暂停中', paused:'已暂停', retrying:'等待续传', failed:'下载失败', cancelled:'已取消', completed:'已下载' };
  const valid = v => !!v && view === v && activePage === 'channels' && document.querySelector('#videoList') === v.grid;
  const itemBody = (x,account) => ({account_id:account,channel_id:x.channel_id,message_id:x.message_id,channel_title:x.channel_title,file_name:x.file_name,size:x.size});
  function stop() {
    if (!view) return;
    view.observer?.disconnect(); view.covers?.disconnect(); clearTimeout(view.poll);
    view.coverQueue.length = 0; view = null;
  }
  // Keep the channel list mounted when opening a video thread, like a chat client.
  window.channels = async function () {
    stop();
    const state = await telegramState(); if (activePage !== 'channels') return;
    if (!state.authorized) {
      content.innerHTML = '<div class="card empty"><h3>连接你的 Telegram</h3><p>登录后浏览频道，将喜欢的视频保存到服务器。</p><button onclick="go(\'telegram\')">扫码 / API 登录</button></div>'; return;
    }
    content.innerHTML = `<div class="channel-client" id="channelClient"><section class="channel-list-pane card" aria-label="频道列表">
      <div class="channel-list-heading"><div><h3>频道</h3><p>你的 Telegram 视频来源</p></div><button class="ghost" id="channelRefresh" aria-label="刷新频道"><svg><use href="#i-refresh"/></svg></button></div>
      <form class="channel-search" id="channelSearchForm"><svg><use href="#i-search"/></svg><input id="channelSearch" type="search" placeholder="搜索频道" aria-label="搜索频道"><button class="ghost" type="submit">搜索</button></form>
      <div id="channelGrid" class="channel-client-list"></div><div class="server-storage-note"><svg><use href="#i-cloud"/></svg><span>下载保存在服务器<br><small>手机关闭网页也能继续下载</small></span></div></section>
      <section id="channelThread" class="channel-thread" aria-label="频道视频"><div class="channel-welcome"><span class="channel-welcome-icon"><svg><use href="#i-chat"/></svg></span><h3>从一个频道开始</h3><p>像浏览聊天一样挑选视频。点亮星标，或将原文件下载到服务器，稍后继续观看。</p><span class="channel-storage-pill"><svg><use href="#i-cloud"/></svg>服务器保存 · 原画播放 · 随时收藏</span></div></section></div>`;
    document.querySelector('#channelSearchForm').onsubmit = event => {event.preventDefault();loadChannels(false);};
    document.querySelector('#channelRefresh').onclick = () => loadChannels(true);
    await loadChannels(false);
  };
  window.loadChannels = async function (refresh = false) {
    const box = document.querySelector('#channelGrid'); if (!box) return;
    const request = ++channelRequest;
    box.innerHTML = '<div class="loading-card"><div class="spinner"></div>正在读取频道…</div>';
    try {
      const items = await api('/channels?q=' + encodeURIComponent(document.querySelector('#channelSearch').value) + (refresh ? '&refresh=true' : ''), {}, 60000);
      if (!box.isConnected || request !== channelRequest) return;
      box.replaceChildren();
      for (const channel of items) {
        const button = document.createElement('button');button.type = 'button';button.className = 'channel-client-item';button.dataset.channelId = channel.id;
        button.innerHTML = `<span class="channel-avatar">${esc(Array.from(channel.title || '频')[0])}</span><span class="channel-copy"><b>${esc(channel.title)}</b><small>${channel.username ? '@' + esc(channel.username) : '私有频道'} · 视频归档</small></span><svg><use href="#i-chevron"/></svg>`;
        button.setAttribute('aria-current', String(valid(view) && Number(view.channel.id) === Number(channel.id)));
        button.onclick = () => openChannel(channel);box.append(button);
      }
      if (!items.length) box.innerHTML = '<div class="empty compact">没有找到频道<br><small>试试其他名称，或刷新频道</small></div>';
    } catch (error) {
      if (box.isConnected && request === channelRequest) {
        box.innerHTML = `<div class="empty compact"><p>${esc(error.message)}</p><button class="ghost">重新加载</button></div>`;
        box.querySelector('button').onclick = () => loadChannels(false);
      }
    }
  };
  function paintState(v, x, card) {
    const status = x.downloaded ? 'completed' : x.download_status;
    const busy = ['queued','downloading','pausing','retrying'].includes(status);
    card.dataset.status = status || 'new';
    if (x.downloaded && x.local_media_id) card.dataset.localMediaId = String(x.local_media_id);
    else delete card.dataset.localMediaId;
    card.querySelector('.catalog-status').textContent = (labels[status] || '未下载') + (status === 'downloading' ? ` ${Math.round(x.download_progress || 0)}%` : '');
    card.querySelector('.catalog-state').textContent = labels[status] || '可加入下载';
    const checkbox = card.querySelector('input');checkbox.disabled = x.downloaded || busy;
    checkbox.checked = selected.has(x.message_id) && !checkbox.disabled;
    if (checkbox.disabled) selected.delete(x.message_id);
    const button = card.querySelector('.catalog-download');
    button.disabled = busy; button.textContent = x.downloaded ? '播放原画' : busy ? labels[status] : ['paused','failed','cancelled'].includes(status) ? '继续下载' : '下载到服务器';
    button.onclick = async () => {
      if (x.downloaded) return x.local_media_id ? play(x.local_media_id) : playSource(x.channel_id,x.message_id);
      button.disabled = true;
      try {
        if (x.download_id && ['paused','failed','cancelled'].includes(status)) await api(`/downloads/${x.download_id}/${status === 'paused' ? 'resume' : 'retry'}`,{method:'POST'});
        else {const result = await api('/downloads',{method:'POST',body:JSON.stringify([itemBody(x,v.account)])});x.download_id=result[0].id;}
        x.download_status='queued';paintState(v,x,card);toast('已加入服务器下载，关闭网页后仍会继续');updateToolbar(v);
      } catch (e) {button.disabled=false;toast(e.message);}
    };
  }
  function updateToolbar(v) {
    if (!valid(v)) return;
    const filter = document.querySelector('#catalogFilter').value, query = document.querySelector('#catalogSearch').value.trim().toLowerCase();
    let shown = 0;
    for (const [id, x] of v.items) {
      const card = v.grid.querySelector(`[data-message-id="${id}"]`);
      const matches = (!query || (x.file_name+' '+(x.caption || '')).toLowerCase().includes(query)) && (filter === 'all' || (filter === 'downloaded' ? x.downloaded : !x.downloaded));
      card.hidden = !matches;if (matches) shown++;
    }
    document.querySelector('#catalogCount').textContent = `已浏览 ${v.items.size} 个视频 · 显示 ${shown} 个`;
    document.querySelector('#queueBtn').textContent = `下载到服务器 (${selected.size})`;
    document.querySelector('#queueBtn').disabled = !selected.size;
    document.querySelector('#catalogEmpty').hidden = shown > 0 || v.loading;
  }
  function drainCovers(v) {
    while (valid(v) && v.coverActive < 3 && v.coverQueue.length) {
      const image = v.coverQueue.shift();if (!image.isConnected) continue;
      v.coverActive++;
      const finish = success => {
        image.onload = image.onerror = null;v.coverActive--;
        image.closest('.catalog-cover').dataset.cover = success ? 'ready' : 'failed';drainCovers(v);
      };
      image.onload = () => finish(true);image.onerror = () => finish(false);image.src = image.dataset.src;
    }
  }
  function append(v, x) {
    if (v.items.has(x.message_id)) return;
    v.items.set(x.message_id,x);
    const card = document.createElement('article');card.className='card catalog-card';card.dataset.messageId=x.message_id;
    const src = `/api/channels/${x.channel_id}/videos/${x.message_id}/thumbnail?account_id=${v.account}&v=3`;
    card.innerHTML = `<div class="catalog-cover" data-cover="loading"><div class="catalog-cover-placeholder"><svg><use href="#i-film"/></svg><small>${x.has_thumbnail || x.local_thumbnail ? '封面加载中' : '来源未提供封面'}</small></div><img alt="视频封面" decoding="async" data-src="${src}"><button class="catalog-cover-retry ghost" type="button">重试封面</button><span class="catalog-status"></span><span class="catalog-duration">${times(x.duration)}</span>${videoFavorites.button({...x,account_id:v.account})}</div>
      <div class="catalog-body"><label><input type="checkbox" aria-label="选择视频"><b title="${esc(mediaPresentation.title(x))}">${esc(mediaPresentation.title(x))}</b></label><p class="muted">${fmt(x.size)} · ${x.width || '—'} × ${x.height || '—'} · ${date(x.date).split(' ')[0]}</p>${mediaPresentation.details(x)}<div class="catalog-card-actions"><small class="catalog-state"></small><button class="catalog-download" type="button"></button></div></div>`;
    v.grid.append(card);
    const image = card.querySelector('img'), cover = card.querySelector('.catalog-cover');
    card.querySelector('.catalog-cover-retry').onclick = () => {cover.dataset.cover='loading';v.coverQueue.push(image);drainCovers(v);};
    if (x.has_thumbnail || x.local_thumbnail) v.covers.observe(image); else cover.dataset.cover='unavailable';
    card.querySelector('input').onchange = event => {event.target.checked ? selected.set(x.message_id,x) : selected.delete(x.message_id);updateToolbar(v);};
    paintState(v,x,card);
  }
  async function load(v) {
    if (!valid(v) || v.loading || !v.more) return;
    v.loading=true;const button=document.querySelector('#catalogMore');button.disabled=true;button.textContent='正在读取更早的视频…';
    try {
      const data = await api(`/channels/${v.channel.id}/videos?offset_id=${v.offset}&limit=24`,{},60000);
      if (!valid(v)) return;
      if (Number(data.account_id) !== v.account) throw Error('账号已切换，请重新打开频道');
      for (const item of data.items) append(v,item);
      v.more=!!data.next_offset_id && data.next_offset_id!==v.offset;v.offset=data.next_offset_id || v.offset;
      v.autoPages++;button.textContent=v.more?'加载更多视频':'已浏览到最早的视频';
    } catch (e) {if(valid(v)){button.textContent='读取失败，点击重试';toast(e.message);v.autoPages=3;}}
    finally {v.loading=false;if(valid(v)){button.disabled=!v.more;updateToolbar(v);}}
  }
  async function refreshTasks(v) {
    if (!valid(v)) return;
    try {
      const jobs=await api('/downloads');if (!valid(v)) return;
      for (const job of jobs) {
        if (Number(job.account_id)!==v.account || Number(job.channel_id)!==Number(v.channel.id)) continue;
        const x=v.items.get(job.message_id);if(!x)continue;
        const completedNow=job.status==='completed' && x.download_status!=='completed';
        x.download_id=job.id;x.download_status=job.status;x.download_progress=job.total_bytes?job.downloaded_bytes/job.total_bytes*100:0;
        if(completedNow) {const local=await api(`/media/source/${x.channel_id}/${x.message_id}`).catch(()=>null);if(!valid(v))return;if(local){x.downloaded=true;x.local_media_id=local.id;}}
        paintState(v,x,v.grid.querySelector(`[data-message-id="${x.message_id}"]`));
      }
      updateToolbar(v);
    } catch {}
    if(valid(v))v.poll=setTimeout(()=>refreshTasks(v),5000);
  }
  window.openChannel = function (channel) {
    const thread = document.querySelector('#channelThread');
    if (valid(view) && Number(view.channel.id) === Number(channel.id)) {
      document.querySelector('#channelClient')?.classList.add('thread-open');
      document.querySelector('#pageTitle').textContent=channel.title;return;
    }
    stop();const id=++run;selected.clear();currentChannel=channel;
    const account=Number(document.querySelector('#accountSelector').value);
    document.querySelector('#pageTitle').textContent=channel.title;
    (thread || content).innerHTML=`<div class="catalog-heading"><button class="ghost" id="catalogBack">← 频道</button><span class="channel-avatar thread-avatar">${esc(Array.from(channel.title || '频')[0])}</span><div><h3>${esc(channel.title)}</h3><p class="muted" id="catalogCount">正在读取视频…</p></div><button class="ghost" id="catalogRefresh">刷新</button></div>
      <div class="thread-storage-note"><svg><use href="#i-cloud"/></svg>下载保存到服务器，完成后在媒体库播放或另存到手机 / 电脑。</div>
      <div class="catalog-toolbar card"><input id="catalogSearch" placeholder="筛选已加载的视频" aria-label="筛选视频"><select id="catalogFilter" aria-label="下载状态筛选"><option value="all">全部视频</option><option value="new">未下载</option><option value="downloaded">已下载</option></select><button class="ghost" id="catalogSelect">全选可下载</button><button id="queueBtn" disabled>下载选中 (0)</button></div>
      <div id="videoList" class="catalog-grid"></div><div id="catalogEmpty" class="card empty" hidden><h3>当前没有匹配的视频</h3><p>可调整筛选，或继续加载更早的视频。</p></div><div class="catalog-pagination"><button class="ghost" id="catalogMore">加载更多视频</button><p class="muted">下滑自动加载，连续三页后可点击继续；选择的视频会保留。</p></div><button class="catalog-to-top ghost" id="catalogTop" aria-label="回到列表顶部">↑ 顶部</button>`;
    const v=view={id,channel,account,grid:document.querySelector('#videoList'),items:new Map(),offset:0,more:true,loading:false,autoPages:0,coverQueue:[],coverActive:0};
    document.querySelector('#channelClient')?.classList.add('thread-open');
    document.querySelectorAll('.channel-client-item').forEach(button => button.setAttribute('aria-current', String(Number(button.dataset.channelId) === Number(channel.id))));
    document.querySelector('#catalogBack').onclick=()=>{const shell=document.querySelector('#channelClient');if(shell){shell.classList.remove('thread-open');document.querySelector('#pageTitle').textContent='频道视频';scrollTo({top:0});}else{stop();go('channels');}};
    document.querySelector('#catalogRefresh').onclick=()=>{stop();openChannel(channel);};
    document.querySelector('#catalogTop').onclick=()=>scrollTo({top:0,behavior:'smooth'});
    document.querySelector('#catalogFilter').onchange=document.querySelector('#catalogSearch').oninput=()=>updateToolbar(v);
    document.querySelector('#catalogSelect').onclick=()=>{const boxes=[...v.grid.querySelectorAll('article:not([hidden]) input:not(:disabled)')];const check=boxes.some(x=>!x.checked);boxes.forEach(x=>{x.checked=check;x.dispatchEvent(new Event('change'));});};
    document.querySelector('#queueBtn').onclick=async()=>{
      if(!selected.size)return;
      const button=document.querySelector('#queueBtn');button.disabled=true;
      try {
        const xs=[...selected.values()].slice(0,100),fresh=xs.filter(x=>!x.download_id || !['paused','failed','cancelled'].includes(x.download_status));
        const mark=(x,id)=>{x.download_id=id;x.download_status='queued';selected.delete(x.message_id);if(valid(v))paintState(v,x,v.grid.querySelector(`[data-message-id="${x.message_id}"]`));};
        let count=0;
        if(fresh.length){const result=await api('/downloads',{method:'POST',body:JSON.stringify(fresh.map(x=>itemBody(x,v.account)))});result.forEach((row,i)=>{mark(fresh[i],row.id);if(!row.duplicate)count++;});}
        for(const x of xs.filter(x=>!fresh.includes(x))){await api(`/downloads/${x.download_id}/${x.download_status==='paused'?'resume':'retry'}`,{method:'POST'});mark(x,x.download_id);count++;}
        if(valid(v)){updateToolbar(v);toast(`已加入 ${count} 个服务器下载任务${selected.size?'；剩余选中项可再次提交':''}`);}
      }catch(e){toast(e.message);if(valid(v))updateToolbar(v);}
    };
    document.querySelector('#catalogMore').onclick=()=>{v.autoPages=0;load(v);};
    v.covers=new IntersectionObserver(entries=>entries.forEach(entry=>{if(entry.isIntersecting){v.covers.unobserve(entry.target);v.coverQueue.push(entry.target);drainCovers(v);}}),{rootMargin:'350px'});
    v.observer=new IntersectionObserver(entries=>{if(entries.some(x=>x.isIntersecting)&&v.autoPages<3)load(v);},{rootMargin:'200px'});
    load(v).then(()=>{if(valid(v))v.observer.observe(document.querySelector('#catalogMore'));});refreshTasks(v);
  };
})();
