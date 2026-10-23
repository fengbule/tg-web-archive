import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const url=process.env.TEST_URL||'http://127.0.0.1:8082';
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox','--autoplay-policy=no-user-gesture-required']});
try {
  const context=await browser.newContext({viewport:{width:1440,height:1000},colorScheme:'light',acceptDownloads:true,hasTouch:true});
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(url);
  assert.equal(await page.locator('html').getAttribute('data-theme'),'light');
  await page.locator('#login [data-theme-toggle]').click();
  await page.reload();assert.equal(await page.locator('html').getAttribute('data-theme'),'dark');
  await page.locator('#adminPassword').fill('fixture-admin-password');await page.locator('#adminLoginButton').click();
  await page.locator('#app').waitFor({state:'visible'});
  for(const theme of ['light','dark']) {
    if(await page.locator('html').getAttribute('data-theme')!==theme) await page.locator('header [data-theme-toggle]').click();
    for(const width of [1440,390,320]) {
      await page.setViewportSize({width,height:width===1440?1000:844});
      await page.waitForTimeout(300);
      for(const route of ['library','accounts','settings']) {
        await page.evaluate(route=>go(route),route);await page.locator('#content .card').first().waitFor();
        assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`${theme} ${width} ${route} overflow`);
        await page.screenshot({path:`/data/workspace/tg-web-archive-e2e/${route}-${theme}-${width}.png`,fullPage:true});
      }
    }
  }
  await page.setViewportSize({width:390,height:844});await page.evaluate(()=>go('accounts'));await page.locator('.account-card').first().waitFor();
  const before=await page.evaluate(()=>fetch('/api/accounts').then(r=>r.json()));
  await page.evaluate(()=>openAccountBackup(1));
  const form=page.locator('#accountBackupForm');
  await form.locator('[name=admin]').fill('wrong-password');
  await form.locator('[name=backup]').fill('browser-backup-password');await form.locator('[name=confirm]').fill('browser-backup-password');
  await form.locator('button[type=submit]').click();await page.getByText('管理员密码错误',{exact:true}).waitFor();
  await form.locator('[name=admin]').fill('fixture-admin-password');
  const downloadPromise=page.waitForEvent('download');await form.locator('button[type=submit]').click();
  const download=await downloadPromise,raw=await fs.readFile(await download.path(),'utf8');
  assert.ok(download.suggestedFilename().endsWith('.nebula'));
  assert.ok(!raw.includes('a'.repeat(32))&&!raw.includes('fixture-admin-password'));
  assert.equal(JSON.parse(raw).format,'nebula-accounts-v1');
  await page.evaluate(()=>openAccountRestore());
  const restore=page.locator('#accountRestoreForm');
  await restore.locator('[name=file]').setInputFiles({name:'accounts.nebula',mimeType:'application/octet-stream',buffer:Buffer.from(raw)});
  await restore.locator('[name=admin]').fill('fixture-admin-password');await restore.locator('[name=backup]').fill('wrong-backup-password');
  await restore.locator('button[type=submit]').click();await page.getByText('备份密码错误，或文件损坏 / 格式不受支持',{exact:true}).waitFor();
  await restore.locator('[name=backup]').fill('browser-backup-password');await restore.locator('button[type=submit]').click();
  await page.locator('#modal').waitFor({state:'hidden'});await page.locator('.account-card').first().waitFor();
  assert.equal((await page.evaluate(()=>fetch('/api/accounts').then(r=>r.json()))).length,before.length,'duplicate must not overwrite or add accounts');
  await page.waitForFunction(async()=> (await fetch('/api/media/1/preview').then(r=>r.json())).status==='ready');
  await page.evaluate(()=>{localStorage.removeItem('tvm-pos-1');play(1)});
  await page.waitForFunction(()=>document.querySelector('#player')?.readyState>=2);
  await page.locator('#seekInput').dispatchEvent('pointerdown',{pointerType:'touch',pointerId:1});
  await page.locator('#seekInput').evaluate(x=>{x.value='7000';x.dispatchEvent(new Event('input',{bubbles:true}))});
  await page.locator('.seek-frame').waitFor({state:'visible'});
  assert.equal(await page.locator('.seek-frame').getAttribute('data-frame'),'2');
  await page.screenshot({path:'/data/workspace/tg-web-archive-e2e/storyboard-mobile.png',fullPage:true});
  await page.locator('#seekInput').dispatchEvent('change');await page.locator('#playerClose').click();
  assert.deepEqual(errors,[]);
  console.log('APPEARANCE_BACKUP_UI=PASS (system theme, persistence, light/dark 3 widths x 3 pages, encrypted download, wrong passwords, duplicate import, real storyboard)');
} finally {await browser.close()}
