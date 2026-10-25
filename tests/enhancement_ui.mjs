import assert from 'node:assert/strict';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const url=process.env.TEST_URL||'http://127.0.0.1:8082';
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox','--autoplay-policy=no-user-gesture-required']});
try {
  const context=await browser.newContext({viewport:{width:390,height:844},hasTouch:true,isMobile:true});
  const page=await context.newPage(),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(url);
  await page.locator('#adminPassword').fill('fixture-admin-password');
  await page.locator('#adminLoginButton').click();await page.locator('#app').waitFor({state:'visible'});
  await page.evaluate(()=>{localStorage.removeItem('tvm-pos-1');play(1)});
  await page.waitForFunction(()=>document.querySelector('#player')?.currentTime>.1);
  assert.equal(await page.locator('#qualityButton').innerText(),'原画');
  await page.locator('#enhanceButton').click();
  const deadline=Date.now()+90000;
  let state;
  while(Date.now()<deadline){
    state=await page.evaluate(()=>fetch('/api/media/1/enhanced').then(r=>r.json()));
    if(state.status==='failed')throw Error(state.error);
    if(state.ready)break;
    await page.waitForTimeout(300);
  }
  assert.equal(state.ready,true,'real enhancement should finish');
  await page.waitForFunction(()=>document.querySelector('#enhanceButton')?.textContent==='播放轻度增强版');
  assert.equal(await page.locator('#qualityButton').innerText(),'原画','generation must not switch quality automatically');
  await page.evaluate(()=>{const v=document.querySelector('#player');v.pause();v.currentTime=8});
  await page.waitForFunction(()=>!document.querySelector('#player').seeking);
  await page.locator('#enhanceButton').click();
  await page.waitForFunction(()=>document.querySelector('#qualityButton')?.textContent==='轻度增强' && document.querySelector('#player')?.readyState>=2);
  assert.ok(await page.locator('#player').evaluate(v=>v.paused&&Math.abs(v.currentTime-8)<.2));
  assert.ok((await page.locator('#downloadButton').getAttribute('href')).includes('quality=enhanced'));
  await page.locator('#skipForward').click();
  await page.waitForFunction(()=>Math.abs(document.querySelector('#player').currentTime-18)<.3);
  const [download]=await Promise.all([page.waitForEvent('download'),page.locator('#enhanceDownload').click()]);
  assert.ok(download.suggestedFilename().includes('轻度增强'));
  assert.equal(await download.failure(),null);
  await page.locator('#enhanceButton').click();
  await page.waitForFunction(()=>document.querySelector('#qualityButton')?.textContent==='原画' && document.querySelector('#player')?.readyState>=2);
  assert.ok(await page.locator('#player').evaluate(v=>v.paused&&Math.abs(v.currentTime-18)<.3));
  for(const width of [320,390,1440]){
    await page.setViewportSize({width,height:width===1440?1000:844});
    for(const theme of ['light','dark']){
      await page.evaluate(t=>document.documentElement.dataset.theme=t,theme);
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
      assert.ok(await page.locator('#enhanceButton').evaluate(e=>{const r=e.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth+1&&r.height>=40}));
      await page.screenshot({path:`/data/workspace/tg-web-archive-e2e/enhancement-${width}-${theme}.png`,fullPage:true});
    }
  }
  // Reopening and changing an episode must retain the original-first policy.
  await page.evaluate(()=>pClosePlayer());await page.evaluate(()=>play(1));
  await page.waitForFunction(()=>document.querySelector('#player')?.currentTime>.1);
  assert.equal(await page.locator('#qualityButton').innerText(),'原画');
  // Exercise cancel controls with a queued task while downloads hold the worker.
  await page.evaluate(()=>pClosePlayer());
  await page.evaluate(()=>fetch('/api/media/1/enhanced',{method:'DELETE'}));
  await page.route('**/api/media/1/enhanced',async route=>{
    if(route.request().method()==='GET')return route.fulfill({json:{id:1,status:'queued',ready:false,progress:0,size:0,error:'',waiting_for_downloads:true}});
    await route.continue();
  });
  await page.evaluate(()=>play(1));await page.locator('#enhanceCancel').waitFor({state:'visible'});
  assert.ok((await page.locator('#enhanceStatus').innerText()).includes('优先下载'));
  const cancelled=page.waitForRequest(r=>r.url().endsWith('/api/media/1/enhanced')&&r.method()==='DELETE');
  await page.locator('#enhanceCancel').click();await cancelled;
  await page.evaluate(()=>pClosePlayer());
  assert.deepEqual(errors,[]);
  console.log('ENHANCEMENT_UI=PASS (real generation, manual quality, pause/position, seeking, device download, original default, cancel, 320/390/1440 light/dark)');
} finally {await browser.close()}
