"""Disposable browser fixture. Never run against production data or expose publicly."""
import asyncio
import base64
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import bcrypt
import uvicorn
from cryptography.fernet import Fernet
from telethon.errors import SessionPasswordNeededError

os.environ['DATA_ROOT']=tempfile.mkdtemp(prefix='tvm-accounts-ui-')
os.environ['SESSION_SECRET']='disposable-browser-fixture-'*4
os.environ['CONFIG_ENCRYPTION_KEY']=Fernet.generate_key().decode()
os.environ['ADMIN_PASSWORD_HASH_B64']=base64.b64encode(bcrypt.hashpw(b'fixture-admin-password',bcrypt.gensalt())).decode()
os.environ['COOKIE_SECURE']='false'
os.environ.pop('TELEGRAM_CLIENT_CONFIG',None)

import app.telegram_service as telegram

states={}; failures=set()

class FakeQR:
    expires=datetime.now(timezone.utc)+timedelta(seconds=30)
    url='tg://login?token=disposable-browser-fixture'
    async def wait(self,timeout=None):
        await asyncio.sleep(.2)
        raise SessionPasswordNeededError(request=None)

class FakeClient:
    def __init__(self,path,*args,**kwargs): self.path=Path(path); self.connected=False
    def is_connected(self): return self.connected
    async def connect(self): self.connected=True; self.path.with_suffix('.session').touch()
    async def disconnect(self): self.connected=False
    async def is_user_authorized(self): return states.get(str(self.path),False)
    async def get_me(self): return SimpleNamespace(first_name='测试',last_name='账号',phone='1234567890')
    async def qr_login(self): return FakeQR()
    async def send_code_request(self,phone):
        assert phone == '+1234567890'
        return SimpleNamespace(phone_code_hash='fixture-code-hash')
    async def sign_in(self,*args,**kwargs):
        if len(args)>1 or 'code' in kwargs:
            assert (args[1] if len(args)>1 else kwargs['code']) == '12345'
            raise SessionPasswordNeededError(request=None)
        assert kwargs['password']=='fixture-2fa-password'
        states[str(self.path)]=True
    async def log_out(self):
        if str(self.path) in failures: raise ConnectionError('Fixture network failure')
        states[str(self.path)]=False
        return True
    async def iter_dialogs(self,*args,**kwargs):
        for item in []: yield item

telegram.TelegramClient=FakeClient
from app.main import app,tg
svc=tg.service(); svc.save_api(123456,'fixture-api-hash')
states[str(svc.session_dir/svc.session_name)]=True
(svc.session_dir/(svc.session_name+'.session')).touch()

@app.post('/__test__/fail-logout/{account_id}')
def fail_logout(account_id:int):
    svc=tg.service(account_id); failures.add(str(svc.session_dir/svc.session_name)); return {'ok':True}

@app.delete('/__test__/fail-logout/{account_id}')
def restore_logout(account_id:int):
    svc=tg.service(account_id); failures.discard(str(svc.session_dir/svc.session_name)); return {'ok':True}

# Keep the fixture-only controls ahead of the application's catch-all static mount.
from starlette.routing import Mount
app.router.routes.sort(key=lambda route:isinstance(route,Mount))

if __name__=='__main__': uvicorn.run(app,host='0.0.0.0',port=8000,log_level='warning')
