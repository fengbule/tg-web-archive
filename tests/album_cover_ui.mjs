import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const base=process.env.TEST_URL||'http://127.0.0.1:8082',output=process.env.TEST_OUTPUT||'/data/workspace/tg-web-archive-e2e';await fs.mkdir(output,{recursive:true});
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox','--autoplay-policy=no-user-gesture-required']});
try{
 const page=await browser.newPage({viewport:{width:390,height:844},hasTouch:true}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(base);await page.locator('#adminPassword').fill('fixture-admin-password');await page.locator('#adminLoginButton').click();await page.locator('#app').waitFor({state:'visible'});
 await page.evaluate(()=>go('channels'));await page.locator('.channel-client-item').first().click();
 const card=page.locator('[data-message-id="59"]');await card.waitFor();await card.scrollIntoViewIfNeeded();
 await page.waitForFunction(()=>document.querySelector('[data-message-id="59"] img').naturalWidth===1280);
 const channel=await page.request.get(base+'/api/channels/1/videos/59/thumbnail?account_id=1&v=4');assert.equal(channel.headers()['x-thumbnail-source'],'telegram-album');const poster=await channel.body();
 const jobs=await page.evaluate(()=>api('/downloads'));const job=jobs.find(x=>x.message_id===59);
 await page.evaluate(id=>api('/downloads/'+id+'/resume',{method:'POST'}),job.id);
 let item;const deadline=Date.now()+45000;
 while(Date.now()<deadline){
  const jobs=await page.evaluate(()=>api('/downloads'));
  if(jobs.some(x=>x.message_id===59&&x.status==='completed'))item=(await page.evaluate(()=>api('/media'))).find(x=>x.message_id===59);
  if(item)break;await page.waitForTimeout(200);
 }
 assert.ok(item?.id,'download must finish and publish a media row before checking its cover');const mid=item.id;
 await page.evaluate(()=>go('library'));const local=page.locator(`[data-media-id="${mid}"]`);await local.waitFor();await local.scrollIntoViewIfNeeded();
 const thumb=base+`/api/media/${mid}/thumbnail?v=4`,first=await page.request.get(thumb);assert.equal(first.headers()['x-thumbnail-source'],'telegram-album');assert.deepEqual(await first.body(),poster);assert.equal(first.headers()['cache-control'],'private, no-cache');
 assert.equal((await page.request.get(thumb,{headers:{'If-None-Match':first.headers().etag}})).status(),304,'unchanged images revalidate without resending bytes');
 const anonymous=await browser.newContext();assert.equal((await anonymous.request.get(thumb,{headers:{'If-None-Match':first.headers().etag}})).status(),401);await anonymous.close();
 await page.request.post(base+'/__test__/album-cover-next');await page.locator('#refreshCoversButton').click();await page.waitForFunction(()=>document.querySelector('#refreshCoversButton')?.disabled===false,null,{timeout:45000});
 const changed=await page.request.get(thumb,{headers:{'If-None-Match':first.headers().etag}});assert.equal(changed.status(),200);assert.notEqual(changed.headers().etag,first.headers().etag);assert.notDeepEqual(await changed.body(),poster,'server image changed to the new album photo');
 // A normal page reload keeps HTTP cache and must revalidate the same v=4 URL.
 await page.reload({waitUntil:'domcontentloaded'});await page.locator('#app').waitFor({state:'visible'});
 await page.evaluate(()=>go('library'));await local.waitFor();await local.scrollIntoViewIfNeeded();
 await page.waitForFunction(id=>{
  const image=document.querySelector(`[data-media-id="${id}"] img`);if(!image?.complete||image.naturalWidth!==1280)return false;
  const canvas=document.createElement('canvas');canvas.width=canvas.height=1;const ctx=canvas.getContext('2d');ctx.drawImage(image,0,0,1,1);const pixel=ctx.getImageData(0,0,1,1).data;return pixel[1]>pixel[0];
 },mid,{timeout:15000});
 const pixel=await local.locator('img').evaluate(image=>{const canvas=document.createElement('canvas');canvas.width=canvas.height=1;const ctx=canvas.getContext('2d');ctx.drawImage(image,0,0,1,1);return [...ctx.getImageData(0,0,1,1).data]});
 assert.ok(pixel[1]>pixel[0],'the same browser now shows the green replacement, not its old brown cached image');
 await page.screenshot({path:output+'/album-cover-phone.png'});
 await local.locator('.play-fab').click();await page.locator('#player').waitFor();assert.ok((await page.locator('#player').getAttribute('poster')).includes('thumbnail?v=4'));await page.locator('#playerClose').click();
 assert.deepEqual(errors,[]);console.log('ALBUM_COVER_UI=PASS (exact album poster, downloaded library bytes, same-browser replacement, ETag/304, auth before cache, player poster)');
}finally{await browser.close()}
