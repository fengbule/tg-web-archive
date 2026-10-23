import assert from 'node:assert/strict';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const url=process.env.TEST_URL||'http://127.0.0.1:8082';
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox','--autoplay-policy=no-user-gesture-required']});
let page;
try{
  const context=await browser.newContext({viewport:{width:1440,height:1000},hasTouch:true});
  page=await context.newPage();const errors=[],requests=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>requests.push(r.url()));
  await page.goto(url);await page.locator('#adminPassword').fill('fixture-admin-password');await page.locator('#adminLoginButton').click();
  await page.locator('#app').waitFor({state:'visible'});
  await page.waitForFunction(async()=>{
    const p=await fetch('/api/media/1/playback').then(r=>r.json());
    return p.status==='ready' && (await fetch('/api/media/1/smooth').then(r=>r.json())).ready;
  });
  await page.evaluate(()=>go('library'));await page.locator('.media-card-v2').waitFor();
  await page.screenshot({path:'/data/workspace/tg-web-archive-e2e/library-refined-desktop.png',fullPage:true});
  await page.evaluate(()=>{localStorage.removeItem('tvm-pos-1');play(1)});
  await page.waitForFunction(()=>document.querySelector('#player')?.currentTime>.1);
  assert.equal(await page.locator('#qualityButton').innerText(),'原画');
  assert.ok(requests.some(x=>x.endsWith('/hls/v2/index.m3u8')),'must use original HLS');
  assert.ok(requests.some(x=>x.endsWith('.ts')),'must load muxed progressive TS');
  assert.ok(!(await page.locator('#player').getAttribute('src')).includes('quality=smooth'));
  assert.ok((await page.locator('#player').getAttribute('src')).startsWith('blob:'),'Chromium must use progressive HLS.js');
  await page.evaluate(()=>document.querySelector('#player').pause());
  // Changing the thumb must seek before pointerup, preserve pause, and retain
  // the final target after rapid inputs rather than an earlier queued seek.
  await page.locator('#seekInput').dispatchEvent('pointerdown',{pointerType:'touch',pointerId:1});
  await page.evaluate(()=>{
    const input=document.querySelector('#seekInput');input.value='3000';input.dispatchEvent(new Event('input',{bubbles:true}));
  });
  await page.waitForFunction(()=>document.querySelector('#player').currentTime>7);
  assert.ok(await page.locator('#seekPreview').isVisible());
  await page.locator('.seek-frame').waitFor({state:'visible'});
  assert.ok(await page.locator('.seek-frame').evaluate(x=>x.style.backgroundImage.includes('/preview/sheet-')));
  const writes=await page.evaluate(async()=>{
    const v=document.querySelector('#player'),input=document.querySelector('#seekInput');
    const property=Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype,'currentTime');let writes=0;
    Object.defineProperty(v,'currentTime',{configurable:true,get(){return property.get.call(v)},set(time){writes++;property.set.call(v,time)}});
    for(let n=0;n<12;n++) {input.value=String(4000+n*200);input.dispatchEvent(new Event('input',{bubbles:true}));await new Promise(resolve=>setTimeout(resolve,35))}
    const whileMoving=writes;input.dispatchEvent(new Event('change',{bubbles:true}));const onRelease=writes;
    delete v.currentTime;return {whileMoving,onRelease};
  });
  assert.equal(writes.whileMoving,0,'moving thumbnails should not fetch abandoned full-quality targets');
  assert.equal(writes.onRelease,1,'release should submit the latest original target once');
  await page.locator('#seekInput').dispatchEvent('pointerdown',{pointerType:'touch',pointerId:2});
  await page.evaluate(()=>{
    const input=document.querySelector('#seekInput');for(const value of ['5000','6000','7000']){input.value=value;input.dispatchEvent(new Event('input',{bubbles:true}))}
    window.dispatchEvent(new PointerEvent('pointerup',{pointerType:'touch',pointerId:1}));
  });
  await page.waitForFunction(()=>Math.abs(document.querySelector('#player').currentTime-16.8)<.2);
  assert.equal(await page.locator('#player').evaluate(v=>v.paused),true);
  await page.waitForFunction(()=>!document.querySelector('#player').seeking);
  await page.locator('#qualityButton').click();
  await page.waitForFunction(()=>document.querySelector('#player')?.readyState>=2);
  assert.equal(await page.locator('#qualityButton').innerText(),'480P 流畅');
  assert.ok(await page.locator('#player').evaluate(v=>v.paused&&Math.abs(v.currentTime-16.8)<.3));
  await page.locator('#qualityButton').click();
  await page.waitForFunction(()=>document.querySelector('#player')?.readyState>=2);
  assert.ok(await page.locator('#player').evaluate(v=>v.paused&&Math.abs(v.currentTime-16.8)<.3));
  await page.evaluate(()=>document.querySelector('#player').dispatchEvent(new Event('waiting')));
  await page.waitForTimeout(3100);
  assert.equal(await page.locator('#qualityButton').innerText(),'原画','waiting must never lower quality');
  await page.evaluate(()=>document.querySelector('#player').dispatchEvent(new Event('canplay')));
  assert.ok(await page.locator('#modalBody').evaluate(v=>v.scrollHeight<=v.clientHeight+1),'desktop player controls must fit without scrolling');
  assert.ok(await page.locator('#player').evaluate(v=>v.getBoundingClientRect().height<=document.querySelector('#playerStage').getBoundingClientRect().height+1),'video must fit stage without cropping');
  await page.screenshot({path:'/data/workspace/tg-web-archive-e2e/player-refined-desktop.png',fullPage:true});
  for(const width of [390,320]){
    await page.setViewportSize({width,height:844});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    assert.ok(await page.locator('#modalBody').evaluate(v=>{const r=v.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth+1}),'mobile modal must fit viewport');
    const seek=await page.locator('#seekInput').boundingBox();assert.ok(seek.height>=44);
    for(const id of ['playToggle','muteToggle','speedButton','downloadButton','fullscreenButton']){
      const box=await page.locator('#'+id).boundingBox();assert.ok(box.width>=44&&box.height>=44,id);
    }
    await page.screenshot({path:`/data/workspace/tg-web-archive-e2e/player-refined-${width}.png`,fullPage:true});
  }
  // Real CDP touch input, not just synthetic input/change events.
  await page.setViewportSize({width:390,height:844});
  await page.evaluate(()=>{const v=document.querySelector('#player');v.pause();v.currentTime=8});
  await page.waitForFunction(()=>!document.querySelector('#player').seeking);
  const cdp=await context.newCDPSession(page),box=await page.locator('#player').boundingBox();
  const x=box.x+box.width*.28,y=box.y+box.height*.8;
  await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x,y}]});
  for(let i=1;i<=5;i++){
    await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:x+i*12,y}]});
    await page.waitForTimeout(45);
  }
  assert.ok(await page.locator('#seekPreview').isVisible());
  await page.waitForTimeout(230);
  assert.ok(await page.locator('#player').evaluate(v=>v.currentTime>10),'touch movement must seek while held');
  await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
  await page.waitForFunction(()=>!document.querySelector('#player').seeking);
  assert.ok(await page.locator('#player').evaluate(v=>v.paused&&v.currentTime>10));
  await page.locator('#playToggle').click();await page.waitForFunction(()=>!document.querySelector('#player').paused);
  const range=await page.locator('#seekInput').boundingBox();
  await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:range.x+range.width*.3,y:range.y+range.height/2}]});
  await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:range.x+range.width*.6,y:range.y+range.height/2}]});
  await page.waitForTimeout(180);
  await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
  await page.waitForFunction(()=>!document.querySelector('#player').paused&&!document.querySelector('#player').seeking);
  const current=await page.locator('#player').evaluate(v=>v.currentTime);assert.ok(current>13&&current<16);
  await page.locator('#playerClose').click();await page.locator('#modal').waitFor({state:'hidden'});
  // Deliberately hold half the segment for 8s. The player must decode and
  // play from the first half, before that complete HTTP response arrives.
  let complete=false;
  page.on('requestfinished',r=>{if(r.url().endsWith('/slow-hls/segment-00000.ts'))complete=true});
  await page.route('**/api/media/1/playback',route=>route.fulfill({json:{original:{type:'hls',url:'/__test__/slow-hls/index.m3u8'},status:'ready'}}));
  const before=requests.length;
  await page.evaluate(()=>{localStorage.removeItem('tvm-pos-1');play(1)});
  await page.waitForFunction(()=>document.querySelector('#player')?.currentTime>.15,{},{timeout:6500});
  assert.equal(complete,false,'must play before complete segment response');
  assert.ok(!requests.slice(before).some(x=>x.includes('/stream?')),'must not pass through direct-file fallback');
  await page.locator('#playerClose').click();await page.unroute('**/api/media/1/playback');
  await page.evaluate(()=>go('library'));await page.locator('.media-card-v2').waitFor();
  await page.screenshot({path:'/data/workspace/tg-web-archive-e2e/library-refined-mobile.png',fullPage:true});
  assert.deepEqual(errors,[]);
  console.log('PLAYER_UI=PASS (original HLS, progressive partial response, continuous scrubbing, last target, touch swipe, touch range, pause/resume, quality position, no downgrade, 320/390 touch targets)');
}catch(error){
  console.error(await page?.locator('body').innerText());console.error(await page.evaluate(()=>Object.fromEntries(['modalBody','playerShell','playerStage','playerSpinner'].map(id=>{const e=document.getElementById(id);return [id,e?{rect:e.getBoundingClientRect().toJSON(),height:e.clientHeight,scroll:e.scrollHeight,maxHeight:getComputedStyle(e).maxHeight,opacity:getComputedStyle(e).opacity,class:e.className}:null]}))));throw error;
}finally{await browser.close()}
