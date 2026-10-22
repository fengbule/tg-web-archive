"""Opt-in, private test configuration from Telegram Desktop's public sample.

Telegram permits this sample only for testing, with server-side limitations:
https://core.telegram.org/api/obtaining_api_id
Do not bundle the resulting config with an app released to end users.
"""
import argparse
import json
import os
from pathlib import Path
import re
import urllib.request


def download(url):
    request=urllib.request.Request(url,headers={'User-Agent':'tg-web-archive-private-test'})
    with urllib.request.urlopen(request,timeout=30) as response:
        return response.read().decode()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test-only',action='store_true',required=True)
    parser.parse_args()
    env=Path('.env')
    if not env.exists(): raise SystemExit('Initialize .env first.')
    target=Path('data/config/test-client.json')
    if target.exists(): raise SystemExit('Existing client config preserved; no change.')
    commit=json.loads(download('https://api.github.com/repos/telegramdesktop/tdesktop/commits?path=Telegram/SourceFiles/config.h&sha=dev&per_page=1'))[0]['sha']
    source=f'https://raw.githubusercontent.com/telegramdesktop/tdesktop/{commit}/Telegram/SourceFiles/config.h'
    code=download(source)
    api_id=re.search(r'constexpr auto ApiId = (\d+);',code)
    api_hash=re.search(r'constexpr auto ApiHash = "([a-f0-9]{32})";',code)
    if not api_id or not api_hash: raise SystemExit('Official sample format changed; no configuration written.')
    target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    record={'api_id':int(api_id[1]),'api_hash':api_hash[1],'test_only':True,'source':source,'revision':commit}
    with os.fdopen(os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as f:
        json.dump(record,f)
    lines=env.read_text().splitlines()
    if any(x.startswith('TELEGRAM_CLIENT_CONFIG=') for x in lines):
        raise SystemExit('Client config exists. Update TELEGRAM_CLIENT_CONFIG manually; existing .env preserved.')
    with env.open('a') as f:
        f.write('TELEGRAM_CLIENT_CONFIG=/data/telegram-video-manager/config/test-client.json\n')
    print('Private test client configuration saved. Source revision: '+commit)
    print('Test-only sample is server-limited; production requires your own application credentials.')


if __name__=='__main__': main()
