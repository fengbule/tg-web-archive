let qrPollTimer=null, qrAccount=null, qrRun=0;

function stopQrLogin(){
  clearTimeout(qrPollTimer); qrRun++;
  const account=qrAccount; qrAccount=null;
  if(account!==null)return api('/telegram/qr/cancel?account_id='+account,{method:'POST'}).catch(()=>{});
}

function renderTelegramLogin(s){
  stopQrLogin();
  const account=s.account_id;
  const fields=s.configured?`<p class="status">无需填写 API 凭据，可直接生成二维码。</p>${s.qr_test_mode?'<p class="muted">当前为测试登录模式，可能受到 Telegram 的登录限制。</p>':''}`:`<p><a href="https://my.telegram.org/apps" target="_blank" rel="noreferrer">前往 Telegram 官方页面申请 API ID / API Hash</a></p><label>API ID<input id="inlineApiId" inputmode="numeric" required></label><label>API Hash<input id="inlineApiHash" type="password" required pattern="[a-fA-F0-9]{32}"></label>`;
  content.innerHTML=`<div class="card telegram-login-card"><h3>登录 Telegram 用户账号</h3><p class="muted">用已登录的手机 Telegram 扫码并确认。两步验证密码仅用于当次登录。</p><form id="tgInlineForm">${fields}<div class="actions"><button id="qrStartButton" type="button">生成登录二维码</button><button id="phoneModeButton" class="ghost" type="button">使用手机号验证码</button></div><div id="phoneLoginFields" hidden><label>手机号（含国家区号）<input id="inlinePhone" placeholder="例如：+8613800000000"></label><button>发送验证码</button></div></form><div id="qrLoginPanel" class="qr-login-panel" hidden><img id="qrLoginImage" alt="Telegram 登录二维码" hidden><p id="qrLoginStatus" role="status" aria-live="polite"></p><p class="muted">手机 Telegram → 设置 → 设备 → 连接桌面设备，扫描并确认。二维码会自动刷新，5 分钟后停止等待。</p><button id="qrCancelButton" class="ghost">取消扫码</button></div><div id="inlineError" class="error" role="alert"></div></div>`;
  $('#phoneModeButton').onclick=()=>{stopQrLogin();$('#qrLoginPanel').hidden=true;$('#qrLoginImage').removeAttribute('src');$('#phoneLoginFields').hidden=false;$('#inlinePhone').required=true;$('#inlinePhone').focus()};
  $('#qrCancelButton').onclick=()=>{stopQrLogin();$('#qrLoginPanel').hidden=true;$('#qrLoginImage').removeAttribute('src');$('#qrStartButton').disabled=false};
  $('#qrStartButton').onclick=startQrLogin;
  if(s.configured){
    const own=document.createElement('button');own.type='button';own.className='ghost';own.textContent='使用自己的 API 配置';
    $('#tgInlineForm').append(own);
    own.onclick=()=>{stopQrLogin();$('#qrLoginPanel').hidden=true;$('#qrLoginImage').removeAttribute('src');$('#qrStartButton').disabled=false;own.remove();$('#tgInlineForm').insertAdjacentHTML('afterbegin','<label>API ID<input id="inlineApiId" inputmode="numeric" required></label><label>API Hash<input id="inlineApiHash" type="password" required pattern="[a-fA-F0-9]{32}"></label>')};
  }
  $('#tgInlineForm').onsubmit=async e=>{
    e.preventDefault();stopQrLogin();let err=$('#inlineError');err.textContent='正在连接 Telegram，请稍候…';
    try{await api('/telegram/send-code?account_id='+account,{method:'POST',body:JSON.stringify({...telegramApiFields(),phone:$('#inlinePhone').value})},60000);telegramCodePage(account)}catch(x){err.textContent=x.message}
  };
}

function telegramApiFields(){const value=$('#inlineApiId')?.value;return {api_id:value?+value:null,api_hash:$('#inlineApiHash')?.value||null}}

async function startQrLogin(){
  // Phone fields are optional for QR login; API fields still use native validation.
  $('#inlinePhone').required=false;
  if(!$('#tgInlineForm').reportValidity())return;
  stopQrLogin();const run=qrRun, account=+$('#accountSelector').value;
  qrAccount=account;
  $('#qrStartButton').disabled=true;$('#inlineError').textContent='';
  $('#qrLoginPanel').hidden=false;$('#qrLoginStatus').textContent='正在安全生成二维码…';
  try{
    const state=await api('/telegram/qr/start?account_id='+account,{method:'POST',body:JSON.stringify(telegramApiFields())},60000);
    if(run!==qrRun){api('/telegram/qr/cancel?account_id='+account,{method:'POST'}).catch(()=>{});return}
    $('#inlineApiHash')?.closest('label').remove();$('#inlineApiId')?.closest('label').remove();
    renderQrState(state,run,account);
  }catch(e){if(run===qrRun){$('#inlineError').textContent=e.message;$('#qrLoginStatus').textContent='生成失败，可重试。';$('#qrStartButton').disabled=false}}
}

function renderQrState(s,run,account){
  if(run!==qrRun || activePage!=='telegram' || +$('#accountSelector').value!==account)return;
  if(s.state==='authorized'){stopQrLogin();toast('Telegram 扫码登录成功');go('channels');return}
  if(s.state==='password_needed'){stopQrLogin();telegramPasswordPage(account);return}
  const image=$('#qrLoginImage'),status=$('#qrLoginStatus');
  if(s.state==='waiting'){
    if(image.getAttribute('src')!==s.image)image.src=s.image;
    image.hidden=false;status.textContent='等待手机扫描并确认，二维码过期后自动刷新。';
    qrPollTimer=setTimeout(async()=>{try{const next=await api('/telegram/qr/status?account_id='+account);renderQrState(next,run,account)}catch(e){if(run===qrRun){stopQrLogin();image.hidden=true;image.removeAttribute('src');status.textContent=e.message;$('#qrStartButton').disabled=false}}},1500);
  }else{
    image.hidden=true;image.removeAttribute('src');status.textContent=s.message||(s.state==='expired'?'等待已结束，请重新生成二维码。':'扫码已取消，请重新生成。');$('#qrStartButton').disabled=false;
  }
}

// Stop a pending flow before navigation or an account change can replace its UI.
document.addEventListener('click',e=>{if(e.target.closest('[data-page]'))stopQrLogin()},true);
document.addEventListener('change',e=>{if(e.target.id==='accountSelector')stopQrLogin()},true);
