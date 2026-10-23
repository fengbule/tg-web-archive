import assert from 'node:assert/strict';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
try {
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(process.env.TEST_URL||'http://127.0.0.1:8082');
  await page.locator('#adminPassword').fill('fixture-admin-password');await page.locator('#adminLoginButton').click();
  await page.locator('#app').waitFor({state:'visible'});await page.evaluate(()=>go('channels'));
  await page.waitForFunction(()=>document.querySelector('#content')?.textContent.includes('创作收藏'));
  await page.evaluate(()=>openChannel({id:1,title:'创作收藏 · Studio'}));
  const card=id=>page.locator(`[data-message-id="${id}"]`);
  await card(60).waitFor();assert.equal(await card(60).getAttribute('data-status'),'completed');
  assert.ok(await card(60).locator('input').isDisabled());
  await page.waitForFunction(()=>document.querySelector('[data-message-id="60"] img')?.naturalWidth>0);
  await card(57).scrollIntoViewIfNeeded();await card(57).locator('.catalog-cover-retry').waitFor({state:'visible'});
  await card(57).locator('.catalog-cover-retry').click();
  await page.waitForFunction(()=>document.querySelector('[data-message-id="57"] .catalog-cover')?.dataset.cover==='ready');
  assert.equal(await card(56).locator('.catalog-cover').getAttribute('data-cover'),'unavailable');
  await page.locator('#catalogFilter').selectOption('downloaded');
  assert.equal(await page.locator('.catalog-card:visible').count(),1);
  await page.locator('#catalogFilter').selectOption('all');
  await card(58).locator('input').check();
  await page.locator('#catalogMore').scrollIntoViewIfNeeded();
  await page.waitForFunction(()=>document.querySelectorAll('.catalog-card').length>=48);
  assert.ok(await card(58).locator('input').isChecked(),'pagination keeps selection');
  await page.locator('#catalogMore').scrollIntoViewIfNeeded();
  await page.waitForFunction(()=>document.querySelectorAll('.catalog-card').length===60);
  assert.equal(await page.locator('.catalog-card').count(),new Set(await page.locator('.catalog-card').evaluateAll(xs=>xs.map(x=>x.dataset.messageId))).size);
  assert.ok(await page.locator('#catalogMore').isDisabled());
  await card(59).locator('input').check();
  await page.locator('#queueBtn').click();
  await page.waitForFunction(()=>document.querySelector('[data-message-id="58"]')?.dataset.status==='queued');
  assert.equal(await page.locator('#videoList').count(),1,'queue stays in catalogue');
  assert.equal(await page.locator('#queueBtn').textContent(),'下载选中 (0)');
  await page.waitForFunction(()=>['58','59'].every(id=>document.querySelector(`[data-message-id="${id}"]`)?.dataset.status==='completed'),{},{timeout:30000});
  await card(58).locator('.catalog-download').click();await page.locator('#player').waitFor();await page.locator('#playerClose').click();
  for(const theme of ['light','dark']) {
    if(await page.locator('html').getAttribute('data-theme')!==theme)await page.locator('header [data-theme-toggle]').click();
    for(const width of [1440,390,320]) {
      await page.setViewportSize({width,height:width===1440?1000:844});await page.evaluate(()=>scrollTo(0,0));
      await page.waitForTimeout(250);
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`${theme} ${width} overflow`);
      await page.screenshot({path:`/data/workspace/tg-web-archive-e2e/catalog-${theme}-${width}.png`});
    }
  }
  assert.deepEqual(errors,[]);
  console.log('CATALOG_UI=PASS (real covers/retry, missing-cover fallback, downloaded badges/filter, append scroll/dedup, selection persists, batch resume, live completion/play, light/dark at 3 widths)');
} finally {await browser.close()}
