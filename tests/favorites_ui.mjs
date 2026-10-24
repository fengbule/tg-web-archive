import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const output = process.env.TEST_OUTPUT || '/data/workspace/tg-web-archive-e2e';
await fs.mkdir(output, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true,
  args: ['--no-sandbox', '--autoplay-policy=no-user-gesture-required'] });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, hasTouch: true }), errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(process.env.TEST_URL || 'http://127.0.0.1:8082');
  await page.locator('#adminPassword').fill('fixture-admin-password'); await page.locator('#adminLoginButton').click();
  await page.locator('#app').waitFor({ state: 'visible' });
  const baseline = await page.evaluate(async () => ({ downloads: (await api('/downloads')).length, outbox: (await api('/outbox')).length }));
  await page.evaluate(() => go('library'));
  const local = page.locator('#mediaGrid [data-media-id="1"] .favorite-toggle');
  await local.waitFor(); assert.equal(await local.getAttribute('aria-pressed'), 'false');
  let fail = true;
  await page.route('**/api/favorites', route => route.request().method() === 'PUT' && fail
    ? route.fulfill({ status: 503, json: { detail: 'fixture save unavailable' } }) : route.continue());
  await local.click(); await page.waitForFunction(() => document.querySelector('#toast').textContent.includes('收藏未保存'));
  assert.equal(await local.getAttribute('aria-pressed'), 'false', 'failed save must not claim success');
  fail = false;
  await local.evaluate(button => { button.click(); button.click(); });
  await page.waitForFunction(() => document.querySelector('#mediaGrid .favorite-toggle').getAttribute('aria-pressed') === 'true');
  assert.equal(await page.evaluate(async () => (await api('/favorites')).total), 1);
  await page.reload(); await page.locator('#app').waitFor({ state: 'visible' });
  await page.evaluate(() => go('favorites'));
  await page.locator('#favoriteGrid [data-media-id="1"]').waitFor();
  assert.equal(await page.locator('#favoriteCount').textContent(), '1 个视频');
  await page.locator('#favoriteGrid .play-fab').click(); await page.locator('#player').waitFor();
  assert.equal(await page.locator('#playerFavorite').getAttribute('aria-pressed'), 'true');
  await page.locator('#playerFavorite').click();
  await page.waitForFunction(() => document.querySelector('#playerFavorite').getAttribute('aria-pressed') === 'false');
  await page.locator('#playerFavorite').click();
  await page.waitForFunction(() => document.querySelector('#playerFavorite').getAttribute('aria-pressed') === 'true');
  await page.locator('#playerClose').click();
  await page.evaluate(() => go('channels'));
  await page.waitForFunction(() => document.querySelector('#content')?.textContent.includes('创作收藏'));
  await page.evaluate(() => openChannel({ id: 1, title: '创作收藏 · Studio' }));
  await page.locator('[data-message-id="58"]').waitFor();
  assert.equal(await page.locator('[data-message-id="60"] .favorite-toggle').getAttribute('aria-pressed'), 'true');
  await page.locator('[data-message-id="58"] .favorite-toggle').click();
  await page.waitForFunction(() => document.querySelector('[data-message-id="58"] .favorite-toggle').getAttribute('aria-pressed') === 'true');
  assert.deepEqual(await page.evaluate(async () => ({ downloads: (await api('/downloads')).length, outbox: (await api('/outbox')).length })), baseline);
  await page.evaluate(() => go('favorites'));
  await page.waitForFunction(() => document.querySelectorAll('[data-favorite-entry]').length === 2);
  await page.locator('#favoriteState').selectOption('pending');
  await page.waitForFunction(() => document.querySelectorAll('[data-favorite-entry]').length === 1 && !!document.querySelector('[data-favorite-download="1:1:58"]'));
  await page.locator('#favoriteSearch').fill('不会匹配的名字');
  await page.locator('#favoriteEmpty').waitFor({ state: 'visible' });
  await page.locator('#favoriteSearch').fill('');
  await page.waitForFunction(() => !!document.querySelector('[data-favorite-download="1:1:58"]'));
  // A source bookmark can explicitly enqueue a download and then relink to media.
  await page.locator('[data-favorite-download="1:1:58"]').click();
  await page.waitForFunction(async () => (await api('/downloads')).some(row => row.message_id === 58 && row.status === 'completed'), null, { timeout: 30000 });
  await page.locator('#favoriteState').selectOption('all'); await page.locator('#favoriteRefresh').click();
  await page.waitForFunction(() => document.querySelectorAll('#favoriteGrid [data-media-id]').length === 2);
  const fake = { account_id: 1, channel_id: 1, message_id: 1234, file_name: '<img src=x onerror="window.__xss=true">.mp4', channel_title: '<script>bad</script>' };
  await page.evaluate(item => api('/favorites', { method: 'PUT', body: JSON.stringify(item) }), fake);
  await page.locator('#favoriteRefresh').click();
  await page.waitForFunction(() => document.querySelectorAll('[data-favorite-entry]').length === 3);
  assert.equal(await page.evaluate(() => Boolean(window.__xss)), false);
  assert.ok((await page.locator('#favoriteGrid').textContent()).includes(fake.file_name));
  assert.equal(await page.locator('#favoriteGrid script').count(), 0);
  await page.locator('#favoriteGrid [data-favorite-entry="1:1:1234"] .favorite-toggle').click();
  await page.waitForFunction(() => !document.querySelector('[data-favorite-entry="1:1:1234"]'));
  await page.evaluate(async () => {
    const item = (await api('/channels/1/videos?limit=24')).items.find(item => item.message_id === 57);
    await api('/favorites', { method: 'PUT', body: JSON.stringify({ ...item, account_id: 1 }) });
  });
  await page.locator('#favoriteRefresh').click();
  await page.waitForFunction(() => document.querySelectorAll('[data-favorite-entry]').length === 3);
  for (const theme of ['dark', 'light']) {
    if (await page.locator('html').getAttribute('data-theme') !== theme) await page.locator('header [data-theme-toggle]').click();
    for (const width of [1440, 390, 320]) {
      await page.setViewportSize({ width, height: width === 1440 ? 1000 : 844 });
      await page.waitForTimeout(300);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${theme} ${width} must fit`);
      const star = page.locator('#favoriteGrid .favorite-toggle').first();
      const box = await star.boundingBox(); assert.ok(box.width >= 44 && box.height >= 44);
      await page.screenshot({ path: `${output}/favorites-${theme}-${width}.png`, fullPage: true });
    }
  }
  await page.locator('#favoriteGrid [data-favorite-entry="1:1:57"] .favorite-toggle').tap();
  await page.waitForFunction(() => !document.querySelector('[data-favorite-entry="1:1:57"]'));
  await page.locator('.mobile-nav [data-page="favorites"]').tap();
  await page.locator('#favoriteGrid').waitFor();
  // The Telegram Saved Messages entry remains distinct and callable.
  assert.equal(await page.locator('nav [data-page="saved"]').count(), 1);
  assert.equal(await page.evaluate(() => typeof savedPage), 'function');
  assert.deepEqual(errors, []);
  console.log('FAVORITES_UI=PASS (one-click/retry/double-click, reload persistence, player/library/catalog sync, remote bookmark/download relink, search/filter, safe text, mobile navigation, 44px targets, 320/390/desktop light/dark)');
} finally { await browser.close(); }
