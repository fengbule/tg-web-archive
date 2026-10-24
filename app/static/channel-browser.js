/* Account-scoped catalogue: covers, live task badges, filters and append-only pages. */
(function () {
  'use strict';
  let view = null, run = 0;
  const times = n => `${Math.floor((n || 0) / 60)}:${String(Math.floor((n || 0) % 60)).padStart(2, '0')}`;
  const labels = { queued:'排队中', downloading:'下载中', pausing:'暂停中', paused:'已暂停', retrying:'等待续传', failed:'下载失败', cancelled:'已取消', completed:'已下载' };
  const valid = v => view === v && activePage === 'channels' && document.querySelector('#videoList') === v.grid;
  const itemBody = (x,account) => ({account_id:account,channel_id:x.channel_id,message_id:x.message_id,channel_title:x.channel_title,file_name:x.file_name,size:x.size});
  function stop() {
    if (!view) return;
    view.observer?.disconnect(); view.covers?.disconnect(); clearTimeout(view.poll);
    view.coverQueue.length = 0; view = null;
  }
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
    button.disabled = busy; button.textContent = x.downloaded ? '播放原画' : busy ? labels[status] : ['paused','failed','cancelled'].includes(status) ? '继续下载' : '下载视频';
    button.onclick = async () => {
      if (x.downloaded) return x.local_media_id ? play(x.local_media_id) : playSource(x.channel_id,x.message_id);
      button.disabled = true;
      try {
        if (x.download_id && ['paused','failed','cancelled'].includes(status)) await api(`/downloads/${x.download_id}/${status === 'paused' ? 'resume' : 'retry'}`,{method:'POST'});
        else {const result = await api('/downloads',{method:'POST',body:JSON.stringify([itemBody(x,v.account)])});x.download_id=result[0].id;}
        x.download_status='queued';paintState(v,x,card);toast('已加入下载，继续挑选即可');updateToolbar(v);
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
    document.querySelector('#queueBtn').textContent = `下载选中 (${selected.size})`;
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
    const src = x.local_thumbnail ? `/api/media/${x.local_media_id}/thumbnail` : `/api/channels/${x.channel_id}/videos/${x.message_id}/thumbnail?account_id=${v.account}`;
    card.innerHTML = `<div class="catalog-cover" data-cover="loading"><div class="catalog-cover-placeholder"><svg><use href="#i-film"/></svg><small>${x.has_thumbnail || x.local_thumbnail ? '封面加载中' : '来源未提供封面'}</small></div><img alt="视频封面" decoding="async" data-src="${src}"><button class="catalog-cover-retry ghost" type="button">重试封面</button><span class="catalog-status"></span><span class="catalog-duration">${times(x.duration)}</span>${videoFavorites.button({...x,account_id:v.account})}</div>
      <div class="catalog-body"><label><input type="checkbox" aria-label="选择视频"><b>${esc(x.file_name)}</b></label><p class="muted">${fmt(x.size)} · ${x.width || '—'} × ${x.height || '—'} · ${date(x.date).split(' ')[0]}</p><p class="catalog-caption">${esc(x.caption || '')}</p><div class="catalog-card-actions"><small class="catalog-state"></small><button class="catalog-download" type="button"></button></div></div>`;
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
    stop();const id=++run;selected.clear();currentChannel=channel;
    const account=Number(document.querySelector('#accountSelector').value);
    document.querySelector('#pageTitle').textContent=channel.title;
    content.innerHTML=`<div class="catalog-heading"><button class="ghost" id="catalogBack">← 频道</button><div><h3>${esc(channel.title)}</h3><p class="muted" id="catalogCount">正在读取视频…</p></div><button class="ghost" id="catalogRefresh">刷新</button></div>
      <div class="catalog-toolbar card"><input id="catalogSearch" placeholder="筛选已加载的视频" aria-label="筛选视频"><select id="catalogFilter" aria-label="下载状态筛选"><option value="all">全部视频</option><option value="new">未下载</option><option value="downloaded">已下载</option></select><button class="ghost" id="catalogSelect">全选可下载</button><button id="queueBtn" disabled>下载选中 (0)</button></div>
      <div id="videoList" class="catalog-grid"></div><div id="catalogEmpty" class="card empty" hidden><h3>当前没有匹配的视频</h3><p>可调整筛选，或继续加载更早的视频。</p></div><div class="catalog-pagination"><button class="ghost" id="catalogMore">加载更多视频</button><p class="muted">下滑自动加载，连续三页后可点击继续；选择的视频会保留。</p></div><button class="catalog-to-top ghost" id="catalogTop" aria-label="回到列表顶部">↑ 顶部</button>`;
    const v=view={id,channel,account,grid:document.querySelector('#videoList'),items:new Map(),offset:0,more:true,loading:false,autoPages:0,coverQueue:[],coverActive:0};
    document.querySelector('#catalogBack').onclick=()=>{stop();go('channels');};
    document.querySelector('#catalogRefresh').onclick=()=>openChannel(channel);
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
        if(valid(v)){updateToolbar(v);toast(`已加入 ${count} 个任务，可继续挑选${selected.size?'；剩余选中项可再次提交':''}`);}
      }catch(e){toast(e.message);if(valid(v))updateToolbar(v);}
    };
    document.querySelector('#catalogMore').onclick=()=>{v.autoPages=0;load(v);};
    v.covers=new IntersectionObserver(entries=>entries.forEach(entry=>{if(entry.isIntersecting){v.covers.unobserve(entry.target);v.coverQueue.push(entry.target);drainCovers(v);}}),{rootMargin:'350px'});
    v.observer=new IntersectionObserver(entries=>{if(entries.some(x=>x.isIntersecting)&&v.autoPages<3)load(v);},{rootMargin:'200px'});
    load(v).then(()=>{if(valid(v))v.observer.observe(document.querySelector('#catalogMore'));});refreshTasks(v);
  };
})();
