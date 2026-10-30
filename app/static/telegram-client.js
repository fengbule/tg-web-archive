/* Account-scoped client workspace; drafts live only in this browser tab's memory. */
(() => {
  'use strict';
  let state=null; const drafts=new Map();
  const label={channel:'频道',group:'群组',user:'私聊',bot:'机器人'};
  const account=()=>Number(document.querySelector('#accountSelector')?.value);
  const requestId=()=>crypto.randomUUID?.()||'10000000-1000-4000-8000-100000000000'.replace(/[018]/g,c=>(c^crypto.getRandomValues(new Uint8Array(1))[0]&15>>c/4).toString(16));
  const live=s=>state===s&&s.root.isConnected&&s.account===account()&&activePage==='messages'&&!document.querySelector('#app').hidden;
  const request=(s,path,opt={})=>api('/client'+path+(path.includes('?')?'&':'?')+'account_id='+s.account,opt,45000);
  const post=(s,path,body)=>request(s,path,{method:'POST',body:JSON.stringify(body)});
  const key=s=>s.account+':'+s.peer?.peer_id;
  function error(s,e){if(live(s))toast(e.message||String(e));}
  function run(s,fn){return Promise.resolve().then(fn).catch(e=>error(s,e));}
  function valid(s,room){return live(s)&&s.room===room;}
  window.messagesPage=async function(){
    const root=document.createElement('div');root.className='tg-client card';
    root.innerHTML=`<section class="tg-sidebar"><div class="tg-sidebar-head"><div><b>Telegram</b><small>消息、频道与群组</small></div><button id="tgAdd" class="ghost" aria-label="查找和订阅频道">＋</button></div><input id="tgDialogSearch" type="search" placeholder="搜索已加载会话" aria-label="搜索会话"><div class="tg-tabs" role="group" aria-label="会话分类">${[['all','全部'],['unread','未读'],['channel','频道'],['group','群组'],['user','私聊'],['bot','机器人'],['archive','归档']].map(([v,t])=>`<button class="ghost" data-filter="${v}" aria-pressed="${v==='all'}">${t}</button>`).join('')}</div><div id="tgDialogs" class="tg-dialog-list"></div><button id="tgMoreDialogs" class="ghost">加载更多会话</button><button id="tgRefreshDialogs" class="ghost">刷新会话</button></section><section class="tg-conversation"><div class="tg-welcome"><span>✉</span><h3>让对话回到手边</h3><p>选择一个会话，或查找频道、群组与好友。</p><p>下载的视频仍保存在服务器媒体库。</p><button id="tgWelcomeAdd">查找 / 加入</button></div></section>`;
    content.replaceChildren(root);
    const s=state={root,account:account(),dialogs:[],cursor:null,filter:'all',room:0,peer:null,messages:new Map(),loading:false,polling:false};
    root.querySelector('#tgAdd').onclick=()=>showTarget(s);root.querySelector('#tgWelcomeAdd').onclick=()=>showTarget(s);
    root.querySelector('#tgDialogSearch').oninput=()=>renderDialogs(s);
    root.querySelector('.tg-tabs').onclick=e=>{const b=e.target.closest('[data-filter]');if(!b)return;const old=s.filter;s.filter=b.dataset.filter;root.querySelectorAll('[data-filter]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));if((old==='archive')!==(s.filter==='archive'))run(s,()=>loadDialogs(s,true));else renderDialogs(s);};
    root.querySelector('#tgMoreDialogs').onclick=()=>run(s,()=>loadDialogs(s,false));root.querySelector('#tgRefreshDialogs').onclick=()=>run(s,()=>loadDialogs(s,true));
    root.querySelector('#tgDialogs').onclick=e=>{const b=e.target.closest('[data-peer]');if(b)run(s,()=>open(s,s.dialogs.find(d=>d.peer_id===Number(b.dataset.peer))));};
    await run(s,()=>loadDialogs(s,true));
    if(live(s))timer=setInterval(()=>{if(!document.hidden)run(s,()=>poll(s));},3500);
  };
  async function loadDialogs(s,reset){
    if(s.listBusy)return;s.listBusy=true;const archived=s.filter==='archive';
    const button=s.root.querySelector('#tgMoreDialogs');button.disabled=true;
    try{
      const x=await request(s,'/dialogs?limit=40&archived='+archived+(!reset&&s.cursor?'&cursor='+encodeURIComponent(s.cursor):''));
      if(!live(s)||archived!==(s.filter==='archive'))return;
      s.dialogs=reset?x.items:[...new Map([...s.dialogs,...x.items].map(d=>[d.peer_id,d])).values()];s.cursor=x.next_cursor;
      renderDialogs(s);
    }finally{s.listBusy=false;if(live(s))button.disabled=false;}
  }
  function renderDialogs(s){
    const q=s.root.querySelector('#tgDialogSearch').value.toLowerCase();
    const xs=s.dialogs.filter(d=>(['all','archive'].includes(s.filter)||s.filter==='unread'&&d.unread_count||d.kind===s.filter)&&(`${d.title} ${d.username||''}`.toLowerCase().includes(q)));
    s.root.querySelector('#tgDialogs').innerHTML=xs.map(d=>`<button class="tg-dialog ${s.peer?.peer_id===d.peer_id?'selected':''}" data-peer="${d.peer_id}"><span class="tg-avatar">${esc(d.title.slice(0,1))}</span><span class="tg-dialog-copy"><b>${esc(d.title)}</b><small>${d.pinned?'⌖ ':''}${esc(d.last_message||label[d.kind]||'会话')}</small></span>${d.unread_count?`<span class="tg-unread">${d.unread_count}</span>`:''}</button>`).join('')||'<p class="tg-empty">当前分类没有匹配会话。可加载更多或查找新目标。</p>';
    s.root.querySelector('#tgMoreDialogs').hidden=!s.cursor;
  }
  async function open(s,peer){
    if(!peer||!live(s))return;saveDraft(s);const room=++s.room;s.peer={...peer};s.messages=new Map();s.offset=null;s.after=0;s.reply=null;s.edit=null;s.loading=false;s.polling=false;
    currentDialog={...peer};s.root.classList.add('tg-open');renderDialogs(s);
    s.root.querySelector('.tg-conversation').innerHTML=`<header class="tg-chat-head"><button id="tgBack" class="ghost" aria-label="返回会话列表">←</button><div class="tg-chat-title"><b>${esc(peer.title)}</b><small>${esc(label[peer.kind]||'会话')}${peer.username?' · @'+esc(peer.username):''}</small></div><button id="tgTools" class="ghost" aria-label="会话操作">⋯</button></header><div class="tg-chat-tools" hidden><button data-action="read">标为已读</button><button data-action="pin">置顶</button><button data-action="mute">静音</button><button data-action="archive">归档</button><button data-action="leave" class="danger">退出频道 / 群组</button></div><form class="tg-message-search"><input type="search" id="tgMessageQuery" placeholder="搜索此会话消息" maxlength="200" aria-label="搜索此会话消息"><button class="ghost">搜索</button><button type="button" id="tgReload" class="ghost">刷新</button></form><div class="tg-timeline" tabindex="0" aria-label="消息记录"><button id="tgOlder" class="ghost">加载更早消息</button><div id="tgMessages"></div><div id="tgHistoryError" class="error" role="status"></div></div><button id="tgBottom" class="ghost" hidden>有新消息 ↓</button><div id="tgComposeContext" hidden></div><form id="tgCompose" class="tg-compose"><textarea id="tgText" rows="2" maxlength="4096" aria-label="消息内容" placeholder="输入消息…"></textarea><button type="submit">发送</button></form><small id="tgComposeHint" class="tg-compose-hint">Enter 换行 · Ctrl / ⌘ + Enter 发送 · 草稿仅保留在当前标签页</small>`;
    const root=s.root,box=root.querySelector('#tgText');box.value=drafts.get(key(s))||'';box.oninput=()=>saveDraft(s);
    root.querySelector('#tgCompose button').type='submit';
    const attachment=document.createElement('button');attachment.type='button';attachment.className='ghost';attachment.textContent='＋';attachment.setAttribute('aria-label','从服务器媒体库发送视频');attachment.onclick=()=>run(s,()=>files(s));root.querySelector('#tgCompose').prepend(attachment);
    const uploads=document.createElement('small');uploads.id='tgUploadStatus';uploads.className='tg-compose-hint';root.querySelector('.tg-conversation').append(uploads);
    box.onkeydown=e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)&&!e.isComposing){e.preventDefault();root.querySelector('#tgCompose').requestSubmit();}};
    root.querySelector('#tgCompose').onsubmit=e=>{e.preventDefault();run(s,()=>send(s));};
    root.querySelector('#tgBack').onclick=()=>{saveDraft(s);s.room++;s.peer=null;s.root.classList.remove('tg-open');currentDialog=null;renderDialogs(s);};
    root.querySelector('#tgTools').onclick=()=>{const el=root.querySelector('.tg-chat-tools');el.hidden=!el.hidden;};
    root.querySelector('.tg-chat-tools').onclick=e=>{const b=e.target.closest('[data-action]');if(b)run(s,()=>action(s,b));};
    root.querySelector('.tg-message-search').onsubmit=e=>{e.preventDefault();run(s,()=>history(s,true));};
    root.querySelector('#tgReload').onclick=()=>{root.querySelector('#tgMessageQuery').value='';run(s,()=>history(s,true));};
    root.querySelector('#tgOlder').onclick=()=>run(s,()=>history(s,false));root.querySelector('#tgBottom').onclick=()=>bottom(s);
    root.querySelector('#tgMessages').onclick=e=>run(s,async()=>{
      const b=e.target.closest('[data-message-action],[data-bot]');if(!b)return;const m=s.messages.get(Number(b.closest('[data-message-id]').dataset.messageId));
      if(b.dataset.bot){const [row,col]=b.dataset.bot.split(':').map(Number);const x=await post(s,`/dialogs/${s.peer.peer_id}/messages/${m.id}/click`,{row,col});if(x.answer)toast(x.answer);return;}
      if(b.dataset.messageAction==='delete'){
        if(!confirm('为双方删除这条自己发送的消息？此操作不可撤销。'))return;
        await request(s,`/dialogs/${s.peer.peer_id}/messages/${m.id}`,{method:'DELETE'});if(!valid(s,room))return;s.messages.delete(m.id);renderMessages(s);return;
      }
      if(b.dataset.messageAction==='edit'){s.edit=m;s.reply=null;box.value=m.text||'';}else{s.reply=m;s.edit=null;}
      context(s);box.focus();
    });
    await history(s,true);
    if(!valid(s,room))return;
    try{const info=await request(s,`/dialogs/${peer.peer_id}`);if(!valid(s,room))return;s.peer={...s.peer,...info};currentDialog=s.peer;}catch(e){error(s,e);}
    if(!valid(s,room))return;updateTools(s);
  }
  function updateTools(s){
    const p=s.peer,root=s.root;
    root.querySelector('[data-action=pin]').textContent=p.pinned?'取消置顶':'置顶';root.querySelector('[data-action=mute]').textContent=p.muted?'取消静音':'静音';root.querySelector('[data-action=archive]').textContent=p.archived?'移出归档':'归档';root.querySelector('[data-action=leave]').hidden=!p.can_leave;
    root.querySelector('#tgText').disabled=p.can_send===false;root.querySelectorAll('#tgCompose button').forEach(b=>b.disabled=p.can_send===false);
    if(p.can_send===false)root.querySelector('#tgComposeHint').textContent='当前频道只读，或账号受禁言限制。订阅后可在这里查看消息。';
  }
  function saveDraft(s){if(!s?.peer||!s.root.isConnected||s.edit)return;const text=s.root.querySelector('#tgText')?.value||'';if(text)drafts.set(key(s),text);else drafts.delete(key(s));}
  function context(s){const el=s.root.querySelector('#tgComposeContext'),m=s.edit||s.reply;el.hidden=!m;el.innerHTML=m?`<b>${s.edit?'编辑消息':'回复 '+esc(m.sender)}</b><span>${esc((m.text||'附件').slice(0,100))}</span><button class="ghost" aria-label="取消回复或编辑">×</button>`:'';if(m)el.querySelector('button').onclick=()=>{if(s.edit)s.root.querySelector('#tgText').value=drafts.get(key(s))||'';s.edit=null;s.reply=null;context(s);};}
  function bubble(m){
    const actions=`<details><summary aria-label="消息操作">⋯</summary><div><button data-message-action="reply">回复</button>${m.out?'<button data-message-action="edit">编辑</button><button data-message-action="delete">删除</button>':''}</div></details>`;
    const buttons=(m.buttons||[]).map(row=>`<div class="tg-bot-buttons">${row.map(b=>b.url?`<a href="${safeUrl(b.url)}" target="_blank" rel="noreferrer">${esc(b.text)}</a>`:`<button data-bot="${b.row}:${b.col}">${esc(b.text)}</button>`).join('')}</div>`).join('');
    return `<article data-message-id="${m.id}" class="tg-bubble ${m.out?'out':''}"><b>${esc(m.out?'我':m.sender)}</b>${m.reply_to_id?`<small>回复 #${m.reply_to_id}</small>`:''}<div class="tg-message-text">${esc(m.text||'')}</div>${m.media?`<div class="tg-attachment">📎 ${esc(m.media.name)} · ${fmt(m.media.size)}${m.media.local_media_id?`<button onclick="play(${Number(m.media.local_media_id)})">播放服务器原画</button>`:''}</div>`:''}${buttons}<footer><time>${date(m.date)}</time>${m.edited?' · 已编辑':''}${actions}</footer></article>`;
  }
  function renderMessages(s){s.root.querySelector('#tgMessages').innerHTML=[...s.messages.values()].sort((a,b)=>a.id-b.id).map(bubble).join('')||'<p class="tg-empty">没有消息</p>';}
  function bottom(s){const el=s.root.querySelector('.tg-timeline');el.scrollTop=el.scrollHeight;s.root.querySelector('#tgBottom').hidden=true;}
  async function history(s,reset){
    if(s.loading||!s.peer)return;s.loading=true;const room=s.room,query=s.root.querySelector('#tgMessageQuery').value.trim();
    const button=s.root.querySelector('#tgOlder');button.disabled=true;
    try{
      const x=await request(s,`/dialogs/${s.peer.peer_id}/messages?limit=40&q=${encodeURIComponent(query)}`+(!reset&&s.offset?'&offset_id='+s.offset:''));if(!valid(s,room))return;
      const scroll=s.root.querySelector('.tg-timeline'),oldHeight=scroll.scrollHeight,oldTop=scroll.scrollTop;
      if(reset){s.messages.clear();s.after=0;s.query=query;}
      x.items.forEach(m=>{s.messages.set(m.id,m);s.after=Math.max(s.after,m.id);});s.offset=x.next_offset_id;
      renderMessages(s);button.hidden=!s.offset;s.root.querySelector('#tgHistoryError').textContent='';
      if(reset)bottom(s);else scroll.scrollTop=oldTop+scroll.scrollHeight-oldHeight;
    }catch(e){if(valid(s,room)){s.root.querySelector('#tgHistoryError').textContent=e.message;button.hidden=false;}}
    finally{if(valid(s,room)){s.loading=false;button.disabled=false;}}
  }
  async function poll(s){
    if(!live(s)||!s.peer||s.query||s.loading||s.polling)return;s.polling=true;const room=s.room;
    try{
      const x=await request(s,`/dialogs/${s.peer.peer_id}/messages?after_id=${s.after}&limit=40`);if(!valid(s,room)||s.query)return;
      const scroll=s.root.querySelector('.tg-timeline'),nearBottom=scroll.scrollHeight-scroll.scrollTop-scroll.clientHeight<80;let added=false;
      x.items.forEach(m=>{if(!s.messages.has(m.id))added=true;s.messages.set(m.id,m);s.after=Math.max(s.after,m.id);});
      if(added){renderMessages(s);if(nearBottom)bottom(s);else s.root.querySelector('#tgBottom').hidden=false;}
    }finally{if(valid(s,room))s.polling=false;}
  }
  async function send(s){
    if(!s.peer||s.sending||s.peer.can_send===false)return;
    const input=s.root.querySelector('#tgText'),text=input.value;if(!text.trim())return;
    const room=s.room,peer=s.peer.peer_id,edit=s.edit,reply=s.reply,draftKey=key(s),button=s.root.querySelector('#tgCompose button[type=submit]');
    s.sending=true;button.disabled=true;button.textContent='发送中…';
    try{
      const path=`/dialogs/${peer}/messages`,m=edit?await request(s,path+'/'+edit.id,{method:'PATCH',body:JSON.stringify({text})}):await post(s,path,{text,reply_to:reply?.id||null,request_id:requestId()});
      if(!edit&&drafts.get(draftKey)===text)drafts.delete(draftKey);if(!valid(s,room))return;
      if(input.value===text)input.value='';s.edit=null;s.reply=null;context(s);s.messages.set(m.id,m);s.after=Math.max(s.after,m.id);renderMessages(s);bottom(s);
    }finally{s.sending=false;if(valid(s,room)){button.disabled=false;button.textContent='发送';}}
  }
  async function action(s,b){
    if(!s.peer||b.disabled)return;const room=s.room,p=s.peer,a=b.dataset.action;
    if(a==='leave'&&!confirm(`退出“${p.title}”？私有频道可能需要邀请才能重新加入。服务器已下载的视频会保留。`))return;
    b.disabled=true;
    try{
      await post(s,`/dialogs/${p.peer_id}/actions`,{action:a,enabled:!p[{pin:'pinned',mute:'muted',archive:'archived'}[a]],max_id:s.after});if(!valid(s,room))return;
      if(a==='read'){p.unread_count=0;const row=s.dialogs.find(d=>d.peer_id===p.peer_id);if(row)row.unread_count=0;}
      else if(a==='leave'||a==='archive'){saveDraft(s);s.room++;s.peer=null;currentDialog=null;s.root.classList.remove('tg-open');s.root.querySelector('.tg-conversation').innerHTML='<p class="tg-empty">操作已完成，请选择会话。</p>';await loadDialogs(s,true);return;}
      else{p[a==='pin'?'pinned':'muted']=!p[a==='pin'?'pinned':'muted'];updateTools(s);}
      renderDialogs(s);toast('操作已完成');
    }finally{b.disabled=false;}
  }
  async function files(s){
    const room=s.room,peer=s.peer?.peer_id;if(!peer||s.peer.can_send===false)return;
    const xs=await api('/media?sort=time');if(!valid(s,room))return;if(!xs.length)return toast('服务器媒体库里还没有视频');
    modal(`<h3>发送服务器视频</h3><p class="muted">文件保留在服务器。发送到 Telegram 会加入后台上传队列，遵守来源内容保护。</p><form id="tgFileForm"><label>选择视频<select id="tgFileId">${xs.map(x=>`<option value="${x.id}">${esc(x.file_name)} · ${fmt(x.size)}</option>`).join('')}</select></label><label>附带文字<input id="tgFileCaption" maxlength="1024"></label><button>确认发送</button></form><div id="tgFileError" class="error"></div>`);
    const form=document.querySelector('#tgFileForm'),err=document.querySelector('#tgFileError');
    form.onsubmit=async e=>{e.preventDefault();if(!valid(s,room))return;const button=form.querySelector('button');button.disabled=true;
      try{const media_id=Number(document.querySelector('#tgFileId').value),caption=document.querySelector('#tgFileCaption').value;
        const check=await api(`/media/${media_id}/sendability`,{},45000);if(!valid(s,room)||!form.isConnected)return;if(!check.allowed)throw Error(check.reason||'此来源不允许重新发送');
        const job=await api('/outbox',{method:'POST',body:JSON.stringify({account_id:s.account,peer_id:peer,media_id,caption})});if(!valid(s,room)||!form.isConnected)return;closeModal();toast(`已加入上传队列 #${job.id}，可在 Telegram 收藏夹 / 发送队列中查看`);s.root.querySelector('#tgUploadStatus').textContent=`视频上传任务 #${job.id} 已排队，服务器后台继续发送。`;
      }catch(e){if(err.isConnected)err.textContent=e.message;}finally{button.disabled=false;}
    };
  }
  function showTarget(s){
    if(!live(s))return;const room=s.room;
    modal(`<h3>发现与订阅</h3><p class="muted">查找好友、机器人、频道或群组。预览不会自动加入。</p><form id="tgTargetForm"><label>@用户名或邀请链接<input id="tgTarget" placeholder="@channel 或 https://t.me/+…" maxlength="300" required></label><button>预览</button></form><div id="tgTargetResult"></div><div id="tgTargetError" class="error" role="status"></div>`);
    const form=document.querySelector('#tgTargetForm'),result=document.querySelector('#tgTargetResult'),err=document.querySelector('#tgTargetError');
    form.onsubmit=async e=>{e.preventDefault();const target=document.querySelector('#tgTarget').value;form.querySelector('button').disabled=true;err.textContent='';result.replaceChildren();
      try{const p=await post(s,'/target/preview',{target});if(!live(s)||!form.isConnected)return;
        result.innerHTML=`<div class="tg-target-card"><span class="tg-avatar">${esc(p.title.slice(0,1))}</span><h3>${esc(p.title)}</h3><p>${esc(label[p.kind]||'会话')}${p.username?' · @'+esc(p.username):''}${p.request_needed?' · 需要管理员批准':''}</p><div class="actions">${p.peer_id?'<button data-target="open" class="ghost">打开对话</button>':''}${p.kind!=='user'&&!p.already_member?`<button data-target="join">${p.kind==='bot'?'启动机器人':p.request_needed?'申请加入':'加入 / 订阅'}</button>`:''}</div></div>`;
        result.onclick=async event=>{const b=event.target.closest('[data-target]');if(!b)return;if(!live(s))return;
          if(b.dataset.target==='open'){closeModal();run(s,()=>open(s,p));return;}
          b.disabled=true;try{const joined=await post(s,'/target/join',{target});if(!live(s)||!form.isConnected)return;closeModal();toast(joined.status==='requested'?'已申请，等待管理员批准':'已加入 / 已启动');await loadDialogs(s,true);if(joined.peer_id)await open(s,joined);}catch(e){if(err.isConnected)err.textContent=e.message;}finally{b.disabled=false;}
        };
      }catch(e){if(err.isConnected)err.textContent=e.message;}finally{form.querySelector('button').disabled=false;}
    };
  }
  // Expose only navigation helpers; account IDs and peer IDs remain captured above.
  window.telegramClient={open:peer=>state&&run(state,()=>open(state,peer)),refresh:()=>state&&run(state,()=>loadDialogs(state,true))};
  window.showJoinDialog=async()=>{await go('messages');if(state)showTarget(state);};
})();
