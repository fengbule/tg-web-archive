import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const url = process.env.TEST_URL || 'http://127.0.0.1:8082';
const output = process.env.TEST_OUTPUT || '/data/workspace/tg-web-archive-e2e';
await fs.mkdir(output, { recursive: true });
const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true,
  args: ['--no-sandbox', '--autoplay-policy=no-user-gesture-required'],
});
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, hasTouch: true });
  const page = await context.newPage(), errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(url);
  await page.locator('#adminPassword').fill('fixture-admin-password');
  await page.locator('#adminLoginButton').click();
  await page.locator('#app').waitFor({ state: 'visible' });
  await page.waitForFunction(async () => (await fetch('/api/media/1/playback').then(r => r.json())).status === 'ready');
  await page.evaluate(() => { localStorage.removeItem('tvm-pos-1'); play(1); });
  await page.waitForFunction(() => document.querySelector('#player')?.currentTime > .1);
  await page.locator('#player').evaluate(video => { video.loop = true; });
  const paused = () => page.locator('#player').evaluate(video => video.paused);
  const hidden = () => page.locator('#playerShell').evaluate(shell => shell.classList.contains('controls-hidden'));
  const cdp = await context.newCDPSession(page);
  const tapPicture = async () => {
    const box = await page.locator('#playerStage').boundingBox();
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: box.x + box.width / 2, y: box.y + box.height / 2 }] });
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  };
  const reveal = async () => { if (await hidden()) await tapPicture(); };
  // Real mouse and touch clicks on the picture never change playback state.
  await page.locator('#player').click();
  assert.equal(await paused(), false, 'mouse click must not pause');
  await reveal();
  await page.locator('#playToggle').click();
  assert.equal(await paused(), true);
  await page.waitForFunction(() => document.querySelector('#playToggle').getAttribute('aria-label') === '播放');
  assert.equal(await page.locator('#playToggle').getAttribute('aria-label'), '播放');
  await page.locator('#player').click();
  assert.equal(await paused(), true, 'picture click must not resume a paused video');
  assert.equal(await page.locator('#playerStage button').count(), 0, 'no button may cover the picture');
  await page.screenshot({ path: output + '/player-controls-desktop.png', fullPage: true });
  for (const theme of ['dark', 'light']) {
    await page.locator('html').evaluate((html, value) => html.dataset.theme = value, theme);
    for (const width of [390, 320]) {
      await page.setViewportSize({ width, height: 844 });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      const stage = await page.locator('#playerStage').boundingBox();
      for (const id of ['playToggle', 'skipBack', 'skipForward', 'muteToggle', 'speedButton', 'downloadButton', 'fullscreenButton']) {
        const box = await page.locator('#' + id).boundingBox();
        assert.ok(box.width >= 44 && box.height >= 44, id + ' needs a 44px touch target');
        assert.ok(box.y >= stage.y + stage.height - 1, id + ' must be below the picture');
        assert.ok(box.x >= 0 && box.x + box.width <= width + 1, id + ' must fit the screen');
      }
      await tapPicture();
      assert.equal(await paused(), true, 'touch must preserve paused state');
      await page.locator('#playToggle').tap();
      await page.mouse.move(0, 0);
      await page.waitForFunction(() => document.querySelector('#playerShell').classList.contains('controls-hidden'), {}, { timeout: 5000 });
      const before = await page.locator('#playerStage').boundingBox();
      await tapPicture();
      assert.equal(await hidden(), false, 'touch must reveal controls');
      assert.equal(await paused(), false, 'revealing controls must not pause');
      const after = await page.locator('#playerStage').boundingBox();
      assert.deepEqual(after, before, 'revealing controls must not resize or move the picture');
      await tapPicture();
      assert.equal(await hidden(), true, 'second touch must hide controls');
      assert.equal(await paused(), false);
      await tapPicture();
      await page.locator('#playToggle').tap();
      assert.equal(await paused(), true, 'only the playback button pauses on tap');
      assert.equal(await hidden(), false, 'paused video must keep the controls available');
      await page.screenshot({ path: `${output}/player-controls-${theme}-${width}.png`, fullPage: true });
    }
  }
  // A held seek and keyboard focus must never lose their controls to the timer.
  await page.locator('#playToggle').tap();
  const seek = await page.locator('#seekInput').boundingBox();
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: seek.x + seek.width * .35, y: seek.y + seek.height / 2 }] });
  await page.waitForTimeout(3300);
  assert.equal(await hidden(), false, 'controls must remain available while holding the seek bar');
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await page.waitForFunction(() => !document.querySelector('#player').paused);
  await page.keyboard.press('Tab');
  await page.locator('#playToggle').focus();
  await page.waitForTimeout(3300);
  assert.equal(await hidden(), false, 'keyboard focus must keep controls available');
  await page.setViewportSize({ width: 844, height: 390 });
  await page.locator('#fullscreenButton').tap();
  await page.waitForFunction(() => document.fullscreenElement?.id === 'playerShell');
  await page.mouse.move(0, 0);
  await page.waitForFunction(() => document.querySelector('#playerShell').classList.contains('controls-hidden'), {}, { timeout: 5000 });
  await page.waitForFunction(() => getComputedStyle(document.querySelector('.player-controls')).visibility === 'hidden'
    && getComputedStyle(document.querySelector('.player-top')).visibility === 'hidden');
  assert.ok(await page.evaluate(() => {
    const stage = document.querySelector('#playerStage').getBoundingClientRect();
    return stage.height >= innerHeight - 1 && document.elementFromPoint(innerWidth / 2, innerHeight / 2)?.tagName === 'VIDEO';
  }), 'fullscreen idle view must give the entire screen to the video');
  await page.screenshot({ path: output + '/player-controls-fullscreen.png' });
  await tapPicture();
  assert.equal(await paused(), false, 'fullscreen touch must not pause');
  await page.locator('#playToggle').tap();
  assert.equal(await paused(), true);
  await page.evaluate(() => document.exitFullscreen());
  await page.locator('#playerClose').click();
  await page.evaluate(() => play(1));
  await page.locator('#playToggle').waitFor();
  await page.locator('#playerClose').click();
  await page.waitForTimeout(3300);
  assert.deepEqual(errors, []);
  console.log('PLAYER_CONTROLS_UI=PASS (mouse/touch isolation, bottom controls, 320/390 light/dark, idle timer, stable layout, held seek, keyboard focus, fullscreen, close/reopen)');
} finally { await browser.close(); }
