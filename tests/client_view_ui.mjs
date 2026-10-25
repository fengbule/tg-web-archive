import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const output = process.env.TEST_OUTPUT || '/data/workspace/tg-web-archive-e2e';
await fs.mkdir(output, {recursive:true});
const browser = await chromium.launch({executablePath:process.env.CHROMIUM_PATH || '/usr/bin/chromium',headless:true,args:['--no-sandbox','--autoplay-policy=no-user-gesture-required']});
try {
  const page = await browser.newPage({viewport:{width:1440,height:1000},hasTouch:true}), errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(process.env.TEST_URL || 'http://127.0.0.1:8082');
  await page.locator('#adminPassword').fill('fixture-admin-password');await page.locator('#adminLoginButton').click();
  await page.locator('#app').waitFor({state:'visible'});
  const mode = async value => {
    await page.locator('#viewModeButton').click();
    const panel = await page.locator('#viewModePanel').boundingBox();
    assert.ok(panel.x >= 0 && panel.x + panel.width <= page.viewportSize().width + 1, 'view options remain inside screen');
    await page.locator(`[data-view-choice=${value}]`).click();
    await page.waitForFunction(value => document.documentElement.dataset.viewMode === value, value);
  };
  const noOverflow = async label => assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth + 1), label + ' horizontal overflow');
  assert.equal(await page.locator('html').getAttribute('data-layout'),'desktop');
  await page.evaluate(()=>go('channels'));await page.locator('.channel-client-item').first().waitFor();
  assert.equal(await page.locator('.channel-client-item').first().getAttribute('aria-current'),'false');
  await page.locator('.channel-client-item').first().click();
  const card = id => page.locator(`.catalog-card[data-message-id="${id}"]`);
  await card(58).locator('input').check();
  await page.evaluate(()=>window.__selectedCard=document.querySelector('[data-message-id="58"]'));
  for (const value of ['phone','tablet','desktop']) {
    await page.evaluate(()=>scrollTo(0,0));await mode(value);
    assert.ok(await card(58).locator('input').isChecked());
    assert.ok(await page.evaluate(()=>window.__selectedCard===document.querySelector('[data-message-id="58"]')),'switch must retain catalogue DOM');
    await noOverflow(value);
  }
  await mode('phone');await page.locator('#catalogBack').click();
  assert.ok(await page.locator('.channel-list-pane').isVisible());assert.ok(!await page.locator('#channelThread').isVisible());
  await page.locator('.channel-client-item').first().click();assert.ok(await card(58).locator('input').isChecked(),'back keeps selected items');
  await page.locator('#catalogBack').click();await page.locator('#channelSearch').fill('not-a-channel');await page.locator('#channelSearch').press('Enter');
  await page.getByText('没有找到频道').waitFor();
  await page.locator('#channelSearch').fill('');await page.locator('#channelSearch').press('Enter');await page.locator('.channel-client-item').first().click();
  assert.ok(await card(58).locator('input').isChecked(),'search keeps open thread');
  await page.evaluate(()=>scrollTo(0,0));await page.locator('#viewModeButton').click();
  await page.keyboard.press('End');assert.equal(await page.locator('[data-view-choice=desktop]').evaluate(x=>x===document.activeElement),true);
  await page.keyboard.press('Escape');assert.ok(!await page.locator('#viewModePanel').isVisible());
  assert.ok(await page.locator('#viewModeButton').evaluate(x=>x===document.activeElement));
  await page.reload();await page.locator('#app').waitFor({state:'visible'});
  assert.equal(await page.locator('html').getAttribute('data-view-mode'),'phone','manual choice persists');
  // A mode change must preserve the actual video, time and playback settings.
  await page.evaluate(()=>go('library'));await page.locator('[data-media-id="1"] .play-fab').click();
  await page.locator('#player').waitFor();await page.waitForFunction(()=>document.querySelector('#player').readyState>=2);
  await page.evaluate(()=>{window.__video=document.querySelector('#player');__video.pause();__video.currentTime=7;__video.playbackRate=1.5;__video.volume=.4;});
  // Simulate another tab switching layout while a modal is open.
  await page.evaluate(()=>dispatchEvent(new StorageEvent('storage',{key:'nebula-view-mode',newValue:'tablet'})));
  assert.equal(await page.locator('html').getAttribute('data-layout'),'tablet');
  const player = await page.evaluate(()=>({same:__video===document.querySelector('#player'),time:__video.currentTime,speed:__video.playbackRate,volume:__video.volume,paused:__video.paused}));
  assert.ok(player.same);assert.ok(Math.abs(player.time-7)<1);assert.equal(player.speed,1.5);assert.ok(Math.abs(player.volume-.4)<.01);assert.ok(player.paused);
  await page.locator('#playerClose').click();
  assert.ok(await page.locator('[data-media-id="1"] [onclick="pDownload(1)"]').getAttribute('aria-label').then(x=>x.includes('手机')));
  const downloadEvent = page.waitForEvent('download');await page.locator('[data-media-id="1"] [onclick="pDownload(1)"]').click();
  const download = await downloadEvent;assert.ok(download.suggestedFilename().endsWith('.mp4'));assert.ok((await fs.stat(await download.path())).size>0);
  // Verify queue destination using the isolated fixture, never a real account/file.
  await page.evaluate(()=>go('channels'));await page.locator('.channel-client-item').first().click();
  await card(58).waitFor();assert.match(await card(58).locator('.catalog-download').textContent(),/服务器/);
  const queueResponse = page.waitForResponse(r=>r.url().endsWith('/api/downloads') && r.request().method()==='POST');
  await card(58).locator('.catalog-download').click();assert.equal((await queueResponse).status(),200);
  await page.waitForFunction(()=>document.querySelector('[data-message-id="58"]').dataset.status==='completed',null,{timeout:30000});
  await page.evaluate(()=>go('library'));await page.locator('[data-media-id="2"]').waitFor();
  await page.evaluate(()=>go('favorites'));await page.locator('#favoriteSearch').waitFor();
  for (const theme of ['light','dark']) {
    if (await page.locator('html').getAttribute('data-theme') !== theme) await page.locator('header [data-theme-toggle]').click();
    for (const width of [320,390,768,1024,1440]) {
      await page.setViewportSize({width,height:width<600?844:1000});
      for (const value of ['phone','tablet','desktop','auto']) {
        await mode(value);await page.waitForTimeout(80);await noOverflow(`${theme} ${width} ${value}`);
        assert.ok(await page.locator('#viewModeButton').isVisible());
      }
    }
    // Real channel screenshots at each intended physical size, plus forced phone on desktop.
    for (const [width,value] of [[390,'phone'],[768,'tablet'],[1440,'desktop'],[1440,'phone']]) {
      await page.setViewportSize({width,height:1000});await mode(value);await page.evaluate(()=>go('channels'));
      await page.locator('.channel-client-item').first().click();await card(60).waitFor();await page.waitForTimeout(300);
      await noOverflow(`channel ${width} ${value}`);
      await page.screenshot({path:`${output}/client-view-${theme}-${value}-${width}.png`});
    }
  }
  await mode('auto');await page.setViewportSize({width:390,height:844});
  assert.equal(await page.locator('html').getAttribute('data-layout'),'phone');
  await page.locator('#menu').click();assert.ok(await page.locator('#app > aside').isVisible());
  await page.locator('#app > aside [data-page=messages]').click();await page.locator('.dialog-item').first().click();
  assert.ok(await page.locator('.conversation-pane').isVisible());assert.ok(!await page.locator('.dialog-pane').isVisible());
  await page.locator('.chat-back').click();assert.ok(await page.locator('.dialog-pane').isVisible());
  await page.setViewportSize({width:1024,height:1000});await mode('tablet');
  assert.ok(await page.locator('.dialog-pane').isVisible());assert.ok(await page.locator('.conversation-pane').isVisible());
  assert.deepEqual(errors,[]);
  console.log('CLIENT_VIEW_UI=PASS (3 explicit modes/auto, 40 theme-size combinations, persistence, keyboard, channel split/back/search/selection, live player continuity, server queue/file, real browser save, messages)');
} finally {await browser.close();}
