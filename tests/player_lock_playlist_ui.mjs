import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const url = process.env.TEST_URL || 'http://127.0.0.1:8082';
const output = process.env.TEST_OUTPUT || '/data/workspace/tg-web-archive-e2e';
await fs.mkdir(output, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true,
  args: ['--no-sandbox', '--autoplay-policy=no-user-gesture-required'] });
try {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true });
  await context.addInitScript(() => {
    window.__angle = 0; window.__nativeMode = 'resolve'; window.__locks = []; window.__unlocks = 0;
    Object.defineProperties(screen.orientation, {
      angle: { configurable: true, get: () => window.__angle },
      type: { configurable: true, get: () => Math.abs(window.__angle) % 180 === 90 ? 'landscape-primary' : 'portrait-primary' },
      lock: { configurable: true, value: type => {
        window.__locks.push(type);
        if (window.__nativeMode === 'pending') return new Promise(resolve => { window.__resolveLock = resolve; });
        if (window.__nativeMode === 'reject') return Promise.reject(new DOMException('fixture unsupported', 'NotSupportedError'));
        return Promise.resolve();
      } },
      unlock: { configurable: true, value: () => { window.__unlocks++; } },
    });
  });
  const page = await context.newPage(), errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(url);
  await page.locator('#adminPassword').fill('fixture-admin-password');
  await page.locator('#adminLoginButton').click();
  await page.locator('#app').waitFor({ state: 'visible' });
  await page.waitForFunction(async () => (await fetch('/api/media/1/playback').then(r => r.json())).status === 'ready');
  const fixture = await page.evaluate(() => fetch('/api/media/1').then(r => r.json()));
  fixture.caption = ''; // This suite specifically exercises natural file-name ordering.
  const rows = [
    { ...fixture, id: 1, file_name: '样片 第1集.mp4', channel_id: 1, account_id: 1 },
    { ...fixture, id: 2, file_name: '样片 第2集.mp4', channel_id: 1, account_id: 1 },
    { ...fixture, id: 3, file_name: '样片 第10集.mp4', channel_id: 1, account_id: 1 },
    { ...fixture, id: 4, file_name: '其他账号 第3集.mp4', channel_id: 1, account_id: 2 },
    { ...fixture, id: 5, file_name: '其他频道 第3集.mp4', channel_id: 2, account_id: 1 },
  ];
  let failEpisode = null, delayed = false, sparseList = false;
  // Only the disposable fixture is routed; all episodes decode its real muxed
  // A/V file. Production data is never created, modified or used by this test.
  await page.route('**/api/media**', async route => {
    const request = new URL(route.request().url());
    if (request.pathname === '/api/media') {
      return route.fulfill({ json: request.searchParams.has('q') ? [rows[2], rows[0], rows[1]] : sparseList ? [rows[0]] : [rows[1], rows[2], rows[0], rows[3], rows[4]] });
    }
    const match = request.pathname.match(/^\/api\/media\/(\d+)(.*)$/);
    if (!match) return route.continue();
    const id = Number(match[1]), suffix = match[2];
    if (!suffix && id === failEpisode) return route.fulfill({ status: 404, json: { detail: 'fixture missing episode' } });
    if (!suffix) {
      if (delayed && id === 2) await new Promise(resolve => setTimeout(resolve, 500));
      return route.fulfill({ json: rows.find(row => row.id === id) });
    }
    if (id === 1) return route.continue();
    const response = await route.fetch({ url: request.href.replace(/\/api\/media\/\d+/, '/api/media/1') });
    return route.fulfill({ response });
  });
  const open = async () => {
    await page.evaluate(() => { for (const id of [1, 2, 3]) localStorage.removeItem('tvm-pos-' + id); play(1); });
    await page.waitForFunction(() => document.querySelector('#player')?.currentTime > .1);
    await page.waitForFunction(() => !document.querySelector('#nextEpisode').disabled);
    await page.locator('#player').evaluate(video => { video.loop = true; });
  };
  const reveal = async () => {
    if (await page.locator('#playerShell').evaluate(shell => shell.classList.contains('controls-hidden'))) await page.locator('#player').tap();
  };
  const waitEpisode = async id => {
    await page.waitForFunction(value => document.querySelector('#playerShell')?.dataset.mediaId === String(value)
      && document.querySelector('#player')?.readyState >= 2, id);
  };
  await open();
  await page.evaluate(() => { window.__video = document.querySelector('#player'); window.__shell = document.querySelector('#playerShell'); });
  await reveal(); await page.locator('#lockButton').tap();
  await page.waitForFunction(() => document.querySelector('#playerShell').dataset.lockMethod === 'native');
  assert.equal(await page.locator('#lockButton').getAttribute('aria-pressed'), 'true');
  assert.equal(await page.evaluate(() => document.documentElement.style.overflow), 'hidden');
  assert.equal(await page.evaluate(() => __locks[0]), 'portrait-primary');
  assert.equal(await page.locator('#playerClose').isVisible(), false);
  assert.equal(await page.locator('#fullscreenButton').isVisible(), false);
  assert.equal(await page.locator('#player').evaluate(video => video.paused), false);
  await page.locator('#playToggle').tap();
  await page.locator('#player').evaluate(video => { video.currentTime = 2; video.volume = .4; video.muted = true; });
  await page.locator('#skipForward').tap();
  assert.ok(await page.locator('#player').evaluate(video => video.paused && video.currentTime >= 11.9));
  await page.locator('#speedButton').tap();
  await page.locator('#nextEpisode').tap(); await waitEpisode(2);
  assert.ok(await page.evaluate(() => document.querySelector('#player') === __video && document.querySelector('#playerShell') === __shell));
  assert.equal(await page.evaluate(() => document.fullscreenElement === __shell), true);
  assert.equal(await page.locator('#lockButton').getAttribute('aria-pressed'), 'true');
  assert.ok(await page.locator('#player').evaluate(video => video.paused && video.muted && video.volume === .4 && video.playbackRate === 1.25));
  assert.equal(await page.locator('#qualityButton').innerText(), '原画');
  assert.ok(await page.evaluate(() => Number(localStorage.getItem('tvm-pos-1')) >= 11.9));
  await page.locator('#episodesButton').tap();
  assert.equal(await page.locator('.episode-item').count(), 3, 'same-channel list must exclude other accounts and channels');
  await page.locator('#episodeSearch').fill('10');
  assert.equal(await page.locator('.episode-item').count(), 1);
  await page.locator('[data-episode-id="3"]').tap(); await waitEpisode(3);
  assert.equal(await page.locator('#nextEpisode').isDisabled(), true);
  assert.equal(await page.locator('#episodePanel').isVisible(), false);
  await page.locator('#previousEpisode').tap(); await waitEpisode(2);
  await page.screenshot({ path: output + '/player-lock-portrait.png' });
  // A failed selection leaves the current source and position intact.
  await page.locator('#previousEpisode').tap(); await waitEpisode(1);
  failEpisode = 2;
  await page.locator('#nextEpisode').tap();
  await page.waitForFunction(() => document.querySelector('#toast').textContent.includes('切换失败'));
  assert.equal(await page.locator('#playerShell').getAttribute('data-media-id'), '1');
  failEpisode = null; delayed = true;
  await page.locator('#episodesButton').tap(); await page.locator('#episodeSearch').fill('');
  await page.evaluate(() => { document.querySelector('[data-episode-id="2"]').click(); document.querySelector('[data-episode-id="3"]').click(); });
  await waitEpisode(3); await page.waitForTimeout(650);
  assert.equal(await page.locator('#playerShell').getAttribute('data-media-id'), '3', 'late response must not replace the latest selected episode');
  delayed = false;
  await page.evaluate(() => pClosePlayer());
  await page.waitForFunction(() => !document.fullscreenElement);
  assert.ok(await page.evaluate(() => __unlocks > 0));
  // Library playback keeps the visible search/sort order instead of guessing a series.
  sparseList = true;
  await page.evaluate(() => go('library'));
  await page.waitForFunction(() => document.querySelectorAll('#mediaGrid .media-card-v2').length === 3);
  await open();
  await reveal(); await page.locator('#previousEpisode').tap(); await waitEpisode(3);
  assert.equal(await page.locator('#previousEpisode').isDisabled(), true);
  await page.locator('#nextEpisode').tap(); await waitEpisode(1);
  await page.evaluate(() => pClosePlayer());
  sparseList = false;
  // Reject the native API: rotate only the inner viewport, including controls.
  await page.evaluate(() => { window.__nativeMode = 'reject'; go('dashboard'); });
  await page.locator('.hero').waitFor(); await open();
  await page.locator('#playerShell').evaluate(shell => { shell.requestFullscreen = () => Promise.reject(new DOMException('fixture fullscreen unavailable', 'NotSupportedError')); });
  await reveal(); await page.locator('#lockButton').tap();
  await page.waitForFunction(() => document.querySelector('#playerShell').classList.contains('is-locked'));
  await page.waitForTimeout(200);
  assert.equal(await page.evaluate(() => Boolean(document.fullscreenElement)), false, 'fallback must work without any native fullscreen support');
  await page.setViewportSize({ width: 390, height: 300 });
  assert.ok(await page.locator('#playerViewport').evaluate(element => new DOMMatrixReadOnly(getComputedStyle(element).transform).a > .99), 'keyboard resize must not be mistaken for physical rotation');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => { __angle = 90; });
  await page.setViewportSize({ width: 844, height: 390 });
  await page.evaluate(() => screen.orientation.dispatchEvent(new Event('change')));
  await page.waitForFunction(() => Math.abs(new DOMMatrixReadOnly(getComputedStyle(document.querySelector('#playerViewport')).transform).b) > .99);
  const geometry = await page.locator('#playerViewport').evaluate(element => ({ width: element.clientWidth, height: element.clientHeight, rect: element.getBoundingClientRect().toJSON() }));
  assert.equal(geometry.width, 390); assert.equal(geometry.height, 844);
  assert.ok(geometry.rect.left >= -1 && geometry.rect.top >= -1 && geometry.rect.right <= 845 && geometry.rect.bottom <= 391);
  await reveal(); await page.locator('#playToggle').tap();
  await page.locator('#player').evaluate(video => { video.pause(); video.currentTime = 4; });
  const cdp = await context.newCDPSession(page), box = await page.locator('#playerStage').boundingBox();
  const point = { x: box.x + box.width / 2, y: box.y + box.height / 2 };
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [point] });
  for (let index = 1; index <= 5; index++) {
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: point.x, y: point.y - index * 8 }] });
    await page.waitForTimeout(35);
  }
  await page.waitForTimeout(220);
  assert.ok(await page.locator('#player').evaluate(video => video.currentTime > 4.5), 'rotated swipe must follow the displayed video direction');
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  assert.equal(await page.locator('#player').evaluate(video => video.paused), true);
  await page.locator('#episodesButton').tap();
  await page.screenshot({ path: output + '/player-lock-rotated-playlist.png' });
  await page.locator('#episodeSearch').fill('2'); await page.locator('[data-episode-id="2"]').tap(); await waitEpisode(2);
  assert.equal(await page.locator('#lockButton').getAttribute('aria-pressed'), 'true');
  await page.locator('#lockButton').tap();
  await page.waitForFunction(() => !document.fullscreenElement && !document.querySelector('#playerShell').classList.contains('is-locked'));
  assert.equal(await page.locator('#modalBody #playerShell').count(), 1, 'unlock must restore the original player location');
  assert.equal(await page.evaluate(() => document.documentElement.style.overflow), '');
  await page.evaluate(() => pClosePlayer());
  // Close while native locking is pending: no late global lock or detached player.
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => { __angle = 0; __nativeMode = 'pending'; });
  await open(); await reveal(); await page.locator('#lockButton').tap();
  await page.waitForFunction(() => typeof __resolveLock === 'function');
  await page.evaluate(() => { pClosePlayer(); __resolveLock(); });
  await page.waitForTimeout(200);
  assert.equal(await page.locator('#playerShell').count(), 0);
  assert.equal(await page.evaluate(() => document.documentElement.style.overflow), '');
  assert.equal(await page.evaluate(() => Boolean(document.fullscreenElement)), false);
  assert.deepEqual(errors, []);
  console.log('PLAYER_LOCK_PLAYLIST_UI=PASS (native API path, fallback rotation, rotated touch seek, lock/fullscreen continuity, natural account-scoped order, library order, search, boundaries, per-video progress, failed/rapid selection, late lock cleanup)');
} finally { await browser.close(); }
