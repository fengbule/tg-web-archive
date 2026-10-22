let accountRows=[];

async function accountsPage(){
  const rows=await loadAccounts();
  if(activePage!=='accounts')return;
  content.innerHTML=`<div class="account-page"><div class="account-page-heading"><div><h3>Telegram 账号</h3><p class="muted">为每个账号单独扫码登录，随时切换使用。</p></div><button id="addAccountButton" onclick="addAccount()">＋ 添加账号</button></div><div class="account-list">${rows.map(a=>`<article class="card account-card ${a.active?'is-current':''}" data-account-id="${a.id}"><div class="account-avatar">${esc(a.label.trim().slice(0,1))}</div><div class="account-details"><h3>${esc(a.label)} ${a.active?'<span class="current-account-badge">当前账号</span>':''}</h3><p>${esc(a.name||'')}${a.phone?' · '+esc(a.phone):''}</p><span class="account-state ${a.authorized?'connected':''}">${a.status==='unavailable'?'暂时无法确认登录状态，请刷新':a.authorized?'● 已登录':'○ 未登录'}</span></div><div class="account-card-actions">${a.active?'':`<button class="ghost" data-action="switch" onclick="switchAccount(${a.id})">切换账号</button>`}${!a.authorized?`<button data-action="login" onclick="loginAccount(${a.id})">扫码登录</button>`:''}<button class="ghost" data-action="rename" onclick="renameAccount(${a.id})">重命名</button>${a.authorized!==false||a.session_exists?`<button class="danger ghost-danger" data-action="logout" onclick="endAccountSession(${a.id})">结束会话</button>`:''}${rows.length>1?`<button class="ghost" data-action="remove" onclick="removeAccount(${a.id})">移除账号</button>`:''}</div></article>`).join('')}</div><div class="card account-help"><h3>账号和会话</h3><p>切换账号会保留登录；结束会话会撤销本应用在 Telegram 的登录，下次使用需重新扫码。手机和其他设备上的登录保持有效。</p><p class="muted">每个账号的 Session、消息和下载来源独立保存。已下载视频保留在本地媒体库；退出后台仅退出网页管理端。</p><button class="ghost" onclick="go('accounts')">刷新登录状态</button></div></div>`;
}

function accountNameForm(id=null){
  const row=accountRows.find(a=>a.id===id),editing=id!==null;
  modal(`<h3>${editing?'重命名账号':'添加 Telegram 账号'}</h3><p class="muted">${editing?'用便于识别的名称区分各个账号。':'新账号使用独立登录会话，不会退出现有账号。创建后可直接扫码。'}</p><form id="accountNameForm"><label>账号名称<input id="accountLabel" maxlength="40" required placeholder="例如：工作账号、备用账号" autocomplete="off"></label><div class="actions"><button id="accountSaveButton">${editing?'保存名称':'创建并扫码'}</button><button type="button" class="ghost" onclick="closeModal()">取消</button></div></form><div id="accountError" class="error" role="alert"></div>`);
  $('#accountLabel').value=row?.label||'';
  $('#accountNameForm').onsubmit=async e=>{
    e.preventDefault();const label=$('#accountLabel').value.trim(),error=$('#accountError'),button=$('#accountSaveButton');
    if(!label){error.textContent='请输入账号名称';return}
    button.disabled=true;error.textContent='';
    try{
      await stopQrLogin();
      await api(editing?'/accounts/'+id:'/accounts',{method:editing?'PATCH':'POST',body:JSON.stringify({label})});
      closeModal();await loadAccounts();toast(editing?'账号名称已更新':'新账号已创建，请扫码登录');
      await go(editing?'accounts':'telegram');
    }catch(x){error.textContent=x.message;button.disabled=false}
  };
  $('#accountLabel').focus();
}

function addAccount(){accountNameForm()}
function renameAccount(id){accountNameForm(id)}
async function loginAccount(id){try{await changeAccount(id);await go('telegram')}catch(e){toast(e.message)}}

function endAccountSession(id,remove=false){
  const row=accountRows.find(a=>a.id===id);
  if(!row)return;
  const title=remove?'移除账号':'结束会话';
  modal(`<div class="session-confirm"><div class="session-icon">⇥</div><h3>${title}</h3><p class="session-account-name">${esc(row.label)}</p><p>${remove?'将结束此账号在本应用中的登录，并移除账号入口。':'将结束此账号在本应用中的 Telegram 登录会话。下次使用需要重新扫码。'}</p><p class="muted">手机及其他设备的登录不受影响，已下载视频保留。排队下载会暂停，排队发送会取消；正在运行的任务需先停止。</p><div id="sessionError" class="error" role="alert"></div><div class="actions"><button id="confirmEndSession" class="danger">${remove?'结束会话并移除':'结束会话'}</button><button id="cancelEndSession" class="ghost" onclick="closeModal()">取消</button></div></div>`);
  $('#confirmEndSession').onclick=async()=>{
    const button=$('#confirmEndSession'),error=$('#sessionError');button.disabled=true;button.textContent='正在等待 Telegram 确认…';error.textContent='';
    try{
      await stopQrLogin();
      await api('/accounts/'+id+(remove?'':'/logout'),{method:remove?'DELETE':'POST'},60000);
      closeModal();currentDialog=null;currentChannel=null;selected.clear();selectedMedia.clear();
      await loadAccounts();await telegramState();toast(remove?'账号已移除':'Telegram 会话已结束');await go('accounts');
    }catch(e){error.textContent=e.message;button.disabled=false;button.textContent=remove?'结束会话并移除':'结束会话'}
  };
  $('#cancelEndSession').focus();
}

function removeAccount(id){endAccountSession(id,true)}
function tgLogout(){endAccountSession(+$('#accountSelector').value)}
