import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const url=process.env.TEST_URL||'http://127.0.0.1:8082';
const output=process.env.TEST_OUTPUT||'/data/workspace/tg-web-archive-e2e';
await fs.mkdir(output,{recursive:true});
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox','--enable-unsafe-swiftshader','--autoplay-policy=no-user-gesture-required']});
const errors=[],writes=[];
async function open(context){
  const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(r.method()==='POST'&&r.url().includes('/enhanced'))writes.push(r.url())});
  await page.goto(url);await page.locator('#adminPassword').fill('fixture-admin-password');
  await page.locator('#adminLoginButton').click();await page.locator('#app').waitFor({state:'visible'});
  await page.evaluate(()=>{localStorage.removeItem('tvm-pos-1');play(1)});
  await page.waitForFunction(()=>document.querySelector('#player')?.currentTime>.1);
  return page;
}
async function active(page){await page.waitForFunction(()=>document.querySelector('#realtimeCanvas')?.dataset.active==='true')}
try {
  const context=await browser.newContext({viewport:{width:1440,height:1000},hasTouch:true});
  const page=await open(context);
  assert.equal(await page.locator('#qualityButton').innerText(),'原画');
  assert.equal(await page.locator('#realtimeCanvas').getAttribute('data-mode'),'off');
  assert.equal(await page.locator('#offlineEnhancement').getAttribute('open'),null);
  await page.locator('#player').evaluate(v=>{v.pause();v.currentTime=5});
  await page.waitForFunction(()=>!document.querySelector('#player').seeking);
  await page.locator('#realtimeButton').click();
  const pixels=await page.evaluate(()=>{
    const v=document.querySelector('#player'),canvas=document.querySelector('#realtimeCanvas');
    const before={src:v.currentSrc,time:v.currentTime,paused:v.paused,rate:v.playbackRate,volume:v.volume};
    document.querySelector('[data-realtime-mode="clear"]').click();
    const gl=canvas.getContext('webgl'),w=canvas.width,h=canvas.height,data=new Uint8Array(w*h*4);
    gl.readPixels(0,0,w,h,gl.RGBA,gl.UNSIGNED_BYTE,data);
    const source=document.createElement('canvas');source.width=w;source.height=h;
    const ctx=source.getContext('2d');ctx.drawImage(v,0,0,w,h);const original=ctx.getImageData(0,0,w,h).data;
    let delta=0,changed=0,nonblack=0;
    for(let y=0;y<h;y++)for(let x=0;x<w;x++)for(let c=0;c<3;c++){
      const d=Math.abs(original[(y*w+x)*4+c]-data[((h-1-y)*w+x)*4+c]);delta+=d;if(d>1)changed++;if(data[((h-1-y)*w+x)*4+c]>20)nonblack++;
    }
    return {before,after:{src:v.currentSrc,time:v.currentTime,paused:v.paused,rate:v.playbackRate,volume:v.volume},mean:delta/(w*h*3),changed,nonblack,w,h};
  });
  assert.deepEqual(pixels.before,pixels.after,'enhancement must preserve the only video clock/source');
  assert.ok(pixels.nonblack>10000&&pixels.changed>1000,'shader must actually change nonblank video pixels');
  assert.ok(pixels.mean>.05&&pixels.mean<12,'bounded enhancement must preserve image content/orientation: '+JSON.stringify(pixels));
  assert.equal(await page.locator('video').count(),1);
  for(const mode of ['natural','clear','strong']){
    await page.locator(`[data-realtime-mode=${mode}]`).click();await active(page);
    assert.ok(await page.locator('#player').evaluate(v=>v.paused&&Math.abs(v.currentTime-5)<.1));
  }
  const compare=await page.locator('#realtimeCompare').boundingBox();
  await page.mouse.move(compare.x+compare.width/2,compare.y+compare.height/2);await page.mouse.down();
  assert.equal(await page.locator('#realtimeCanvas').getAttribute('data-active'),'false');
  assert.equal(await page.locator('#player').evaluate(v=>getComputedStyle(v).opacity),'1');
  await page.mouse.up();await active(page);
  await page.locator('#realtimeCompare').focus();await page.keyboard.down('Space');
  assert.equal(await page.locator('#realtimeCanvas').getAttribute('data-active'),'false');await page.keyboard.up('Space');await active(page);
  assert.ok(await page.locator('#player').evaluate(v=>v.paused&&Math.abs(v.currentTime-5)<.1),'keyboard comparison must not trigger the global pause shortcut');
  await page.locator('#realtimeStrength').evaluate(e=>{e.value=82;e.dispatchEvent(new Event('input',{bubbles:true}))});
  assert.equal(await page.locator('#realtimeStrengthValue').innerText(),'82%');
  assert.equal(await page.locator('#realtimeCanvas').getAttribute('data-mode'),'custom');
  await page.locator('#realtimeSplit').click();
  assert.equal(await page.locator('#realtimeCanvas').getAttribute('data-split'),'true');
  await page.locator('#realtimeSplitPosition').evaluate(e=>{e.value=30;e.dispatchEvent(new Event('input',{bubbles:true}))});
  assert.ok(await page.locator('.realtime-frame-labels').evaluate(e=>!e.hidden&&e.style.getPropertyValue('--split')==='30%'));
  await page.locator('#realtimeSplit').click();await page.locator('[data-realtime-mode=strong]').click();
  // No effect is applied to the downloadable file, nor is an enhancement task created.
  assert.ok(!(await page.locator('#downloadButton').getAttribute('href')).includes('quality=enhanced'));
  assert.equal((await page.evaluate(()=>fetch('/api/media/1/enhanced').then(r=>r.json()))).status,'idle');
  await page.locator('#realtimeClose').click();
  await page.locator('#player').evaluate(v=>{v.loop=true;window.__pauses=0;v.addEventListener('pause',()=>window.__pauses++);v.play()});
  await page.waitForFunction(()=>+document.querySelector('#realtimeCanvas').dataset.frames>5);
  await page.locator('#realtimeButton').click();await page.locator('[data-realtime-mode=natural]').click();
  assert.equal(await page.evaluate(()=>window.__pauses),0,'filter changes must not pause audio/video');
  await page.locator('#realtimeClose').click();
  for(const time of [18,3,15]){
    await page.locator('#player').evaluate((v,t)=>v.currentTime=t,time);
    await page.waitForFunction(t=>{const v=document.querySelector('#player'),c=document.querySelector('#realtimeCanvas');return !v.seeking&&c.dataset.active==='true'&&Math.abs(+c.dataset.frameTime-v.currentTime)<.25&&Math.abs(v.currentTime-t)<1},time);
  }
  await page.locator('#player').evaluate(v=>v.pause());
  for(const width of [320,390,1440])for(const theme of ['dark','light']){
    await page.setViewportSize({width,height:width===1440?1000:844});
    await page.evaluate(t=>document.documentElement.dataset.theme=t,theme);
    await page.locator('#realtimeButton').click();
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    for(const selector of ['#realtimeButton','[data-realtime-mode=clear]','#realtimeCompare']){
      const rect=await page.locator(selector).evaluate(e=>{const r=e.getBoundingClientRect();return {width:r.width,height:r.height,left:r.left,right:r.right,screen:innerWidth}});
      assert.ok(rect.width>=44&&rect.height>=44&&rect.left>=0&&rect.right<=width+1,selector+' fits with touch targets '+JSON.stringify(rect));
    }
    await page.screenshot({path:`${output}/realtime-${width}-${theme}.png`,fullPage:true});
    await page.locator('#realtimeClose').click();
  }
  await page.setViewportSize({width:1440,height:1000});
  await page.locator('#fullscreenButton').click();await page.waitForFunction(()=>document.fullscreenElement?.id==='playerShell');
  await page.locator('#realtimeButton').click();await page.locator('[data-realtime-mode=clear]').click();await active(page);
  assert.ok(await page.locator('#realtimePanel').evaluate(e=>document.fullscreenElement.contains(e)));
  await page.locator('#realtimeClose').click();await page.evaluate(()=>document.exitFullscreen());
  // Simulate WebKit presentation notifications: native presentation uses the source video.
  await page.locator('#player').evaluate(v=>v.dispatchEvent(new Event('webkitbeginfullscreen')));
  assert.equal(await page.locator('#realtimeCanvas').getAttribute('data-active'),'false');
  assert.ok((await page.locator('#realtimeStatus').innerText()).includes('原画'));
  await page.locator('#player').evaluate(v=>v.dispatchEvent(new Event('webkitendfullscreen')));await active(page);
  // Resource loss must reveal the existing source, never a black frozen canvas.
  await page.locator('#realtimeCanvas').evaluate(c=>{window.__loseContext=c.getContext('webgl').getExtension('WEBGL_lose_context');window.__loseContext.loseContext()});
  await page.waitForFunction(()=>document.querySelector('#realtimeStatus').textContent.includes('图形资源'));
  assert.equal(await page.locator('#realtimeCanvas').getAttribute('data-active'),'false');
  await page.evaluate(()=>window.__loseContext.restoreContext());await active(page);
  await page.evaluate(()=>pClosePlayer());assert.equal(await page.locator('#realtimeCanvas').count(),0);
  await page.evaluate(()=>play(1));await active(page);
  assert.equal(await page.locator('#realtimeCanvas').getAttribute('data-mode'),'clear');
  assert.equal(await page.locator('#qualityButton').innerText(),'原画');
  await page.locator('#realtimeStrength').evaluate(e=>{e.value=82;e.dispatchEvent(new Event('input',{bubbles:true}))});
  await page.evaluate(()=>{pClosePlayer();play(1,'realtime')});await active(page);
  assert.equal(await page.locator('#realtimeCanvas').getAttribute('data-mode'),'custom');
  assert.equal(await page.locator('#realtimeCanvas').getAttribute('data-strength'),'0.82');
  await page.locator('[data-realtime-mode=off]').click();await page.evaluate(()=>{pClosePlayer();play(1,'realtime')});await active(page);
  assert.equal(await page.locator('#realtimeCanvas').getAttribute('data-mode'),'clear');
  assert.equal(await page.locator('#realtimeCanvas').getAttribute('data-strength'),'0.7');
  await context.close();
  const unsupported=await browser.newContext();
  await unsupported.addInitScript(()=>{const get=HTMLCanvasElement.prototype.getContext;HTMLCanvasElement.prototype.getContext=function(kind,...args){return kind==='webgl'?null:get.call(this,kind,...args)}});
  const noGL=await open(unsupported);await noGL.locator('#realtimeButton').click();await noGL.locator('[data-realtime-mode=natural]').click();
  assert.ok((await noGL.locator('#realtimeStatus').innerText()).includes('无法实时增强'));
  assert.equal(await noGL.locator('#realtimeCanvas').getAttribute('data-active'),'false');
  assert.equal(await noGL.locator('#player').evaluate(v=>v.paused),false);await unsupported.close();
  const fallback=await browser.newContext();await fallback.addInitScript(()=>{delete HTMLVideoElement.prototype.requestVideoFrameCallback;delete HTMLVideoElement.prototype.cancelVideoFrameCallback});
  const raf=await open(fallback);await raf.locator('#realtimeButton').click();await raf.locator('[data-realtime-mode=natural]').click();await active(raf);
  await raf.waitForFunction(()=>+document.querySelector('#realtimeCanvas').dataset.frames>4);
  await raf.locator('#player').evaluate(v=>v.pause());await raf.waitForTimeout(100);
  const frame=await raf.locator('#realtimeCanvas').getAttribute('data-frames');await raf.waitForTimeout(300);
  assert.equal(await raf.locator('#realtimeCanvas').getAttribute('data-frames'),frame,'paused fallback must not busy-loop');await fallback.close();
  assert.deepEqual(writes,[],'real-time enhancement must never request a server-generated copy');assert.deepEqual(errors,[]);
  console.log('REALTIME_ENHANCEMENT_UI=PASS '+JSON.stringify({pixels:{width:pixels.w,height:pixels.h,meanDelta:pixels.mean,changed:pixels.changed},noExtraVideo:true,soleAVClock:true,seeking:true,comparison:true,preferences:true,fullscreen:true,contextLoss:true,noWebGL:true,rafFallback:true,touchLayouts:true}));
} finally {await browser.close()}
