import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const url=process.env.TEST_URL||'http://127.0.0.1:8082',output=process.env.TEST_OUTPUT||'/data/workspace/tg-web-archive-e2e';await fs.mkdir(output,{recursive:true});
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
try{
  const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage(),errors=[],writes=[];
  page.on('pageerror',e=>errors.push(e.message));
  const dialogs=[{peer_id:22,title:'设计讨论组',kind:'group',can_send:true,can_leave:true,unread_count:5},{peer_id:33,title:'频道 · 只读',kind:'channel',can_send:false,can_leave:true,unread_count:3},{peer_id:44,title:'好友 <b>原样</b>',kind:'user',can_send:true,can_leave:false}];
  let rows=Array.from({length:55},(_,i)=>({id:i+1,text:'历史消息 '+(i+1),sender:'测试同事',out:i%2===0,date:new Date().toISOString(),buttons:[]})),delay=false,failSend=false;
  await page.route('**/api/client/**',async route=>{
    const request=route.request(),u=new URL(request.url()),method=request.method(),path=u.pathname.replace('/api/client','');let body={};try{body=request.postDataJSON()||{};}catch{}
    assert.ok(u.searchParams.get('account_id'),'every request must capture an account');
    const reply=json=>route.fulfill({json});
    if(method!=='GET')writes.push({path,body,account:u.searchParams.get('account_id')});
    if(path==='/dialogs')return reply({items:dialogs,next_cursor:null});
    if(path==='/target/preview')return reply({title:'申请加入测试频道',kind:'channel',request_needed:true});
    if(path==='/target/join')return reply({title:'等待管理员批准',status:'requested'});
    const peer=Number(path.split('/')[2]);
    if(path.endsWith('/actions'))return reply({ok:true});
    if(/^\/dialogs\/\d+$/.test(path))return reply(dialogs.find(d=>d.peer_id===peer)||dialogs[0]);
    if(method==='DELETE')return reply({ok:true});
    if(method==='POST'||method==='PATCH'){
      if(failSend){failSend=false;return route.fulfill({status:403,json:{detail:'当前账号没有发言权限'}});}
      const id=method==='PATCH'?Number(path.split('/').at(-1)):100+writes.length;
      const m={id,text:body.text,out:true,sender:'我',date:new Date().toISOString(),reply_to_id:body.reply_to};rows=[...rows.filter(x=>x.id!==id),m];return reply(m);
    }
    if(delay&&peer===22){delay=false;await new Promise(r=>setTimeout(r,600));}
    const after=Number(u.searchParams.get('after_id')),offset=Number(u.searchParams.get('offset_id')),q=u.searchParams.get('q');
    let xs=rows.filter(m=>(!after||m.id>after)&&(!offset||m.id<offset)&&(!q||m.text.includes(q)));
    const more=xs.length>40;xs=after?xs.slice(0,40):xs.slice(-40);
    return reply({items:xs,next_offset_id:!after&&more?xs[0].id:null,has_more:more});
  });
  await page.goto(url);await page.locator('#adminPassword').fill('fixture-admin-password');await page.locator('#adminLoginButton').click();await page.locator('#app').waitFor({state:'visible'});
  await page.evaluate(()=>go('messages'));await page.locator('[data-peer="22"]').click();await page.locator('[data-message-id="55"]').waitFor();
  const scroll=page.locator('.tg-timeline');await scroll.evaluate(el=>el.scrollTop=70);await page.locator('#tgOlder').click();await page.locator('[data-message-id="1"]').waitFor();assert.equal(await page.locator('.tg-bubble').count(),55);
  await page.locator('#tgText').fill('尚未发送的草稿');await page.locator('[data-peer="44"]').click();await page.locator('#tgText').waitFor();assert.equal(await page.locator('#tgText').inputValue(),'');await page.locator('[data-peer="22"]').click();assert.equal(await page.locator('#tgText').inputValue(),'尚未发送的草稿');
  failSend=true;await page.locator('#tgCompose button[type=submit]').click();await page.waitForTimeout(150);assert.equal(await page.locator('#tgText').inputValue(),'尚未发送的草稿');assert.ok(await page.locator('#tgCompose button[type=submit]').isEnabled());
  await page.locator('#tgText').fill('**纯文本** <img src=x onerror=alert(1)>');await page.locator('#tgCompose button[type=submit]').click();await page.waitForFunction(()=>document.querySelector('#tgText').value==='');assert.equal(await page.locator('.tg-message-text img').count(),0);assert.equal(writes.at(-1).account,'1');assert.match(writes.at(-1).body.request_id,/^[0-9a-f-]{36}$/);
  const own=page.locator('.tg-bubble.out').last();await own.locator('summary').click();await own.locator('[data-message-action=reply]').click();await page.locator('#tgText').fill('回复内容');await page.locator('#tgCompose button[type=submit]').click();await page.waitForFunction(()=>document.querySelector('#tgText').value==='');assert.ok(writes.at(-1).body.reply_to);
  const last=page.locator('.tg-bubble.out').last();await last.locator('summary').click();await last.locator('[data-message-action=edit]').click();await page.locator('#tgText').fill('编辑后内容');await page.locator('#tgCompose button[type=submit]').click();await page.waitForFunction(()=>document.querySelector('#tgText').value==='');assert.equal(await page.getByText('编辑后内容',{exact:true}).count(),1);
  await page.locator('#tgMessageQuery').fill('历史消息 5');await page.locator('.tg-message-search button').first().click();await page.waitForFunction(()=>[...document.querySelectorAll('.tg-message-text')].every(e=>e.textContent.includes('历史消息 5')));await page.locator('#tgReload').click();
  await page.locator('#tgTools').click();for(const action of ['pin','mute','read']){await page.locator(`[data-action=${action}]`).click();await page.waitForTimeout(80);}assert.equal(writes.at(-1).body.action,'read');
  await page.locator('[data-peer="33"]').click();await page.waitForFunction(()=>document.querySelector('#tgText').disabled);assert.ok(await page.locator('#tgCompose button[type=submit]').isDisabled());
  await page.locator('#tgAdd').click();await page.locator('#tgTarget').fill('https://t.me/+abc_DEF');await page.locator('#tgTargetForm button').click();await page.locator('[data-target=join]').waitFor();assert.equal(writes.filter(w=>w.path==='/target/join').length,0);await page.locator('[data-target=join]').click();await page.waitForFunction(()=>document.querySelector('#modal').hidden);assert.equal(writes.at(-1).path,'/target/join');assert.match(await page.locator('#toast').innerText(),/等待/);
  // Out-of-order history must not replace the selected peer or a new account.
  delay=true;await page.locator('[data-peer="22"]').click();await page.locator('[data-peer="44"]').click();await page.waitForTimeout(750);assert.match(await page.locator('.tg-chat-title').innerText(),/好友/);
  page.on('dialog',d=>d.accept());await page.locator('[data-peer="22"]').click();await page.locator('#tgTools').click();await page.locator('[data-action=leave]').click();await page.waitForTimeout(150);assert.equal(writes.at(-1).body.action,'leave');
  for(const theme of ['dark','light'])for(const width of [320,390,768,1440]){
    await page.setViewportSize({width,height:width<600?844:1000});await page.evaluate(t=>document.documentElement.dataset.theme=t,theme);
    if(!(await page.locator('[data-peer="22"]').isVisible())&&await page.locator('#tgBack').isVisible())await page.locator('#tgBack').click();
    await page.locator('[data-peer="22"]').click();await page.locator('#tgText').waitFor();
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`${theme} ${width} overflow`);
    const size=await page.locator('#tgCompose button[type=submit]').boundingBox();assert.ok(size.width>=40&&size.height>=44);
    if([390,1440].includes(width))await page.screenshot({path:`${output}/telegram-client-${theme}-${width}.png`});
    if(width<=900)await page.locator('#tgBack').click();
  }
  await page.evaluate(()=>{const sel=document.querySelector('#accountSelector');sel.add(new Option('隔离账号2','2'));sel.value='2';return go('messages');});await page.locator('[data-peer="22"]').click();assert.equal(await page.locator('#tgText').inputValue(),'');await page.locator('#tgText').fill('第二账号');await page.locator('#tgCompose button[type=submit]').click();await page.waitForTimeout(200);assert.equal(writes.at(-1).account,'2');
  assert.deepEqual(errors,[]);console.log('TELEGRAM_CLIENT_UI=PASS (history, reply/edit/search, plaintext escaping, scoped drafts/requests, read/pin/mute, readonly, preview/approval, leave, stale responses, 320/390/768/1440 dark/light)');
}finally{await browser.close();}
