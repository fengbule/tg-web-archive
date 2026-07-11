"""真实浏览器 UI 冒烟测试。通过环境变量传入地址和密码，脚本不保存秘密。"""
import os
from playwright.sync_api import sync_playwright

base=os.environ['TVM_BASE_URL'].rstrip('/')
password=os.environ['TVM_ADMIN_PASSWORD']
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,executable_path=os.getenv('TVM_BROWSER_PATH') or None,args=['--no-proxy-server'])
    page=browser.new_page(viewport={'width':1280,'height':800})
    errors=[]
    page.on('pageerror',lambda e: errors.append(str(e)))
    page.goto(base,wait_until='domcontentloaded',timeout=60000)
    page.locator('#adminPassword').fill(password)
    page.locator('#loginForm button').click()
    page.locator('#app').wait_for(state='visible',timeout=30000)
    assert page.locator('#login').is_hidden()
    assert page.locator('#app').is_visible()
    authorized=page.evaluate("fetch('/api/telegram/status').then(r=>r.json()).then(x=>!!x.authorized)")
    for key,title in [('messages','消息与机器人'),('channels','频道视频'),('downloads','下载任务'),('library','本地媒体库'),('settings','系统设置'),('dashboard','仪表盘')]:
        page.locator(f'aside [data-page="{key}"]').click()
        page.wait_for_function("t => document.querySelector('#pageTitle').textContent === t",arg=title)
        assert page.locator('#content').is_visible()
        if key=='messages' and authorized:
            page.locator('#chatShell').wait_for(state='visible',timeout=60000)
    if not authorized:
        page.locator('aside [data-page="telegram"]').click()
        page.locator('#inlinePhone').wait_for(state='visible',timeout=15000)
    assert not errors,errors
    browser.close()
print('UI_SMOKE=PASS')
