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
from telethon.tl.types import Channel,ChatPhotoEmpty,DocumentAttributeVideo,DocumentAttributeFilename,User

os.environ['DATA_ROOT']=tempfile.mkdtemp(prefix='tvm-accounts-ui-')
os.environ['SESSION_SECRET']='disposable-browser-fixture-'*4
os.environ['CONFIG_ENCRYPTION_KEY']=Fernet.generate_key().decode()
os.environ['ADMIN_PASSWORD_HASH_B64']=base64.b64encode(bcrypt.hashpw(b'fixture-admin-password',bcrypt.gensalt())).decode()
os.environ['COOKIE_SECURE']='false'
os.environ['MIN_FREE_GB']='0'
os.environ.pop('TELEGRAM_CLIENT_CONFIG',None)

import app.telegram_service as telegram

states={}; failures=set(); cover_failures=set()

def video_message(mid):
    return SimpleNamespace(id=mid,message='隔离测试素材 · 横竖屏均可挑选',date=datetime.now(timezone.utc),out=False,reply_to_msg_id=None,edit_date=None,video=SimpleNamespace(
        id=mid,attributes=[DocumentAttributeVideo(duration=24,w=640,h=360),DocumentAttributeFilename(file_name=f'灵感片段 {mid:02d} · 原画.mp4')],
        size=media.stat().st_size,thumbs=[] if mid==56 else [object()]))

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
    async def get_me(self): return User(id=999,first_name='测试',last_name='账号',phone='1234567890')
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
        entity=Channel(id=1,title='创作收藏 · Studio',photo=ChatPhotoEmpty(),date=datetime.now(timezone.utc))
        yield SimpleNamespace(entity=entity,name=entity.title,id=-1000000000001,unread_count=0,pinned=False,folder_id=None,message=None,date=entity.date)
    async def get_entity(self,*args): return SimpleNamespace(title='创作收藏 · Studio')
    async def get_messages(self,entity,ids): return video_message(ids)
    async def iter_messages(self,entity,limit=24,offset_id=0,**kwargs):
        for mid in list(range(min(offset_id-1,60) if offset_id else 60,0,-1))[:limit]: yield video_message(mid)
    async def download_media(self,doc,file,thumb=None):
        if doc.id==57 and doc.id not in cover_failures:
            cover_failures.add(doc.id);raise ConnectionError('Fixture cover temporarily unavailable')
        Path(file).write_bytes(cover.read_bytes());return file
    async def iter_download(self,doc,offset=0,chunk_size=512*1024,**kwargs):
        data=media.read_bytes()
        for start in range(offset,len(data),chunk_size):
            await asyncio.sleep(.3);yield data[start:start+chunk_size]

telegram.TelegramClient=FakeClient
from app.main import app,tg
svc=tg.service(); svc.save_api(123456,'a'*32)
states[str(svc.session_dir/svc.session_name)]=True
from telethon.sessions import SQLiteSession
from telethon.crypto import AuthKey
session=SQLiteSession(str(svc.session_dir/(svc.session_name+'.session')))
session.set_dc(2,'149.154.167.40',443);session.auth_key=AuthKey(b'x'*256);session.save();session.close()

# A real, muxed A/V file in this disposable DATA_ROOT exercises HLS and seeking.
import subprocess
from app.main import ROOT, db
from app.db import now
media=ROOT/'media'/'fixture.mp4'
subprocess.run(['ffmpeg','-nostdin','-y','-v','error','-f','lavfi','-i',
    'testsrc2=size=640x360:rate=24','-f','lavfi','-i','sine=frequency=880:sample_rate=48000',
    '-t','24','-c:v','libx264','-preset','ultrafast','-crf','32','-g','48',
    '-c:a','aac','-movflags','+faststart',str(media)],check=True)
db.execute("INSERT INTO media(channel_id,message_id,channel_title,file_name,file_path,size,duration,width,height,downloaded_at,faststart,smooth_status) "
    "VALUES(1,60,'创作收藏 · Studio','海岸线的二十四秒 · 原画测试.mp4',?,?,24,640,360,?,1,'queued')",
    (str(media),media.stat().st_size,now()))
cover=ROOT/'thumbnails'/'fixture.jpg'
subprocess.run(['ffmpeg','-nostdin','-y','-v','error','-ss','4','-i',str(media),'-frames:v','1','-vf','scale=480:-2',str(cover)],check=True)
db.execute('UPDATE media SET thumb_path=? WHERE id=1',(str(cover),))
for mid,status in [(59,'paused'),(55,'failed')]:
    db.execute('INSERT INTO downloads(channel_id,message_id,channel_title,file_name,total_bytes,status,created_at,updated_at) VALUES(1,?,?,?,?,?,?,?)',
        (mid,'创作收藏 · Studio',f'灵感片段 {mid:02d} · 原画.mp4',media.stat().st_size,status,now(),now()))

@app.get('/__test__/slow-hls/{name}')
def slow_hls(name:str):
    import re
    from fastapi import HTTPException
    from fastapi.responses import FileResponse, StreamingResponse
    if not re.fullmatch(r'(?:index\.m3u8|init\.mp4|segment-[0-9]{5,}\.(?:m4s|ts))',name):raise HTTPException(404)
    path=ROOT/'media/.streams/1'/name
    if not path.is_file():raise HTTPException(404)
    if not name.endswith(('.m4s','.ts')):return FileResponse(path)
    async def chunks():
        data=path.read_bytes();cut=len(data)//2
        yield data[:cut]
        await asyncio.sleep(8)
        yield data[cut:]
    return StreamingResponse(chunks(),media_type='video/mp2t' if name.endswith('.ts') else 'video/mp4')

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
