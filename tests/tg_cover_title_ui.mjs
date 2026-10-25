import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const output=process.env.TEST_OUTPUT||'/data/workspace/tg-web-archive-e2e';await fs.mkdir(output,{recursive:true});
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox','--autoplay-policy=no-user-gesture-required']});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000},hasTouch:true}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 const base=process.env.TEST_URL||'http://127.0.0.1:8082';await page.goto(base);await page.locator('#adminPassword').fill('fixture-admin-password');await page.locator('#adminLoginButton').click();await page.locator('#app').waitFor({state:'visible'});
 const before=await page.evaluate(()=>api('/media/1'));
 await page.evaluate(()=>go('channels'));await page.locator('.channel-client-item').first().click();
 const card=id=>page.locator(`.catalog-card[data-message-id="${id}"]`);await card(60).waitFor();
 await page.waitForFunction(()=>document.querySelector('[data-message-id="60"] img').naturalWidth===960);
 assert.match(await card(60).locator('label b').innerText(),/山海之间 · 第 60 集/);
 assert.ok(!await card(60).locator('.media-source-caption').isVisible());await card(60).locator('summary').click();
 assert.match(await card(60).locator('.media-source-caption').innerText(),/完整 TG 说明/);
 assert.match(await card(60).locator('.media-source-file').innerText(),/灵感片段 60/);
 const tg=await page.request.get(base+'/api/channels/1/videos/60/thumbnail?account_id=1&v=2');assert.equal(tg.headers()['x-thumbnail-source'],'telegram-custom');
 const local=await page.request.get(base+'/api/media/1/thumbnail?v=2');assert.equal(local.headers()['x-thumbnail-source'],'telegram-custom');assert.deepEqual(await tg.body(),await local.body(),'channel and library use the same TG cover, not the local frame');
 await card(58).locator('.favorite-toggle').click();await page.waitForFunction(()=>document.querySelector('[data-message-id="58"] .favorite-toggle').getAttribute('aria-pressed')==='true');
 await page.evaluate(()=>go('favorites'));await page.locator('#favoriteGrid .media-name').waitFor();assert.match(await page.locator('#favoriteGrid .media-name').innerText(),/山海之间 · 第 58 集/);
 await page.locator('#favoriteSearch').fill('日常');await page.waitForTimeout(500);assert.equal(await page.locator('[data-favorite-entry]').count(),1);
 await page.evaluate(()=>go('library'));await page.locator('.media-name').waitFor();assert.match(await page.locator('.media-name').innerText(),/山海之间 · 第 60 集/);
 await page.locator('#mediaSearch').fill('日常');await page.locator('#mediaSearch').press('Enter');await page.waitForTimeout(400);assert.equal(await page.locator('.media-card-v2').count(),1,'caption keyword searches library');
 await page.locator('.play-fab').click();await page.locator('#player').waitFor();assert.match(await page.locator('.player-title h3').innerText(),/山海之间 · 第 60 集/);await page.locator('#playerClose').click();
 assert.equal((await page.evaluate(()=>api('/media/1'))).file_name,before.file_name,'display titles do not rename files');
 const malicious={account_id:1,channel_id:1,message_id:1234,file_name:'opaque-file.mp4',caption:'标题 <img src=x onerror="window.__captionXss=true">\n完整说明 <script>bad()</script>',has_thumbnail:false};
 await page.evaluate(x=>api('/favorites',{method:'PUT',body:JSON.stringify(x)}),malicious);await page.evaluate(()=>go('favorites'));await page.locator('[data-favorite-entry="1:1:1234"]').waitFor();
 await page.locator('[data-favorite-entry="1:1:1234"] summary').click();assert.equal(await page.locator('#favoriteGrid script').count(),0);assert.ok(!await page.evaluate(()=>window.__captionXss));
 await page.evaluate(()=>api('/favorites/1/1/1234',{method:'DELETE'}));
 assert.equal(await page.evaluate(()=>mediaPresentation.title({caption:'https://example.com\n真正的标题',file_name:'raw.mp4'})),'真正的标题');
 assert.equal(await page.evaluate(()=>mediaPresentation.title({caption:'',file_name:'raw.mp4'})),'raw.mp4');
 for(const theme of ['light','dark']){
  if(await page.locator('html').getAttribute('data-theme')!==theme)await page.locator('header [data-theme-toggle]').click();
  for(const width of [320,390,768,1440]){
   await page.setViewportSize({width,height:1000});await page.evaluate(()=>go('channels'));await page.locator('.channel-client-item').first().click();await card(60).waitFor();
   await page.waitForFunction(()=>document.querySelector('[data-message-id="60"] img')?.naturalWidth===960);
   await page.waitForTimeout(200);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   assert.ok(await card(60).locator('label b').evaluate(x=>parseFloat(getComputedStyle(x).fontSize)>=16));
   await card(60).locator('summary').click();assert.ok(await card(60).locator('.media-source-caption').isVisible());
   await page.screenshot({path:`${output}/tg-cover-title-${theme}-${width}.png`});
  }
 }
 assert.deepEqual(errors,[]);console.log('TG_COVER_TITLE_UI=PASS (TG custom cover beats frame, shared library image, message title/details, unchanged file name, caption search/favorites/player, safe text, 8 theme/size screenshots)');
}finally{await browser.close()}
