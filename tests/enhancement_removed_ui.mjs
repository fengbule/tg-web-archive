import assert from 'node:assert/strict';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const url=process.env.TEST_URL||'http://127.0.0.1:8082';
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox','--autoplay-policy=no-user-gesture-required']});
try {
  const context=await browser.newContext({viewport:{width:390,height:844},hasTouch:true});
  await context.addInitScript(()=>{localStorage.setItem('tvm-realtime-enhancement-v1','strong');localStorage.setItem('tvm-realtime-enhancement-v1-strength','1')});
  const page=await context.newPage(),errors=[],requests=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>requests.push(r.url()));
  await page.goto(url);await page.locator('#adminPassword').fill('fixture-admin-password');await page.locator('#adminLoginButton').click();await page.locator('#app').waitFor({state:'visible'});
  assert.ok(await page.evaluate(()=>localStorage.getItem('tvm-realtime-enhancement-v1')===null&&localStorage.getItem('tvm-realtime-enhancement-v1-strength')===null));
  assert.ok(await page.evaluate(()=>typeof attachRealtimeEnhancement==='undefined'&&typeof attachEnhancementControls==='undefined'));
  await page.evaluate(()=>play(1,'enhanced'));await page.waitForFunction(()=>document.querySelector('#player')?.currentTime>.1);
  assert.equal(await page.locator('#qualityButton').innerText(),'原画');
  assert.equal(await page.locator('#realtimeButton,#realtimeCanvas,#realtimePanel,#offlineEnhancement,#enhanceButton,.realtime-frame-labels').count(),0);
  assert.ok(await page.locator('#player').evaluate(v=>getComputedStyle(v).opacity==='1'&&getComputedStyle(v).filter==='none'));
  await page.locator('#player').evaluate(v=>{v.pause();v.currentTime=12});await page.waitForFunction(()=>!document.querySelector('#player').seeking);
  assert.ok(await page.locator('#player').evaluate(v=>v.paused&&Math.abs(v.currentTime-12)<.2));
  for(const width of [320,390,1440])for(const theme of ['dark','light']){
    await page.setViewportSize({width,height:width===1440?1000:844});await page.evaluate(t=>document.documentElement.dataset.theme=t,theme);
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  }
  await page.evaluate(()=>pClosePlayer());await page.evaluate(()=>pMediaMenu(1));
  assert.ok(!(await page.locator('#modal').innerText()).includes('增强'));
  assert.equal(requests.filter(url=>/enhance|\/enhanced/.test(url)).length,0,'no removed assets or background API polling');
  for(const path of ['/enhancement.js','/enhancement.css','/realtime-enhancement.js','/realtime-enhancement.css'])assert.equal((await page.request.get(url+path)).status(),404);
  assert.deepEqual(errors,[]);console.log('ENHANCEMENT_REMOVED_UI=PASS (stale preferences removed, no controls/filter/canvas/API, original seeking, 320/390/1440 light/dark, removed assets 404)');
} finally {await browser.close()}
