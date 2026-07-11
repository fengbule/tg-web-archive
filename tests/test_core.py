import os, tempfile
import asyncio, threading
from datetime import datetime, timezone
from types import SimpleNamespace
from pathlib import Path
os.environ.setdefault('SESSION_SECRET','x'*64)
os.environ.setdefault('ADMIN_PASSWORD_HASH_B64','JDJiJDEyJExRdjNjMXlxQldWSHhrZDBMSEFrQ09ZejZU dHhNL2dpUERTU1ZYekJNenJCdW43YzZSQnpH'.replace(' ',''))
os.environ.setdefault('CONFIG_ENCRYPTION_KEY','hTt_JVQy8yrH8b8fAoJmM3LhsBVKk24g4pLfqq1JR10=')
from app.db import Database
from app.downloader import Downloader
from app.telegram_service import TelegramAccountService
from telethon.tl.types import User

class TG: active_id=1
def test_schema_and_duplicate():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)
        for d in ('media','temp','thumbnails'): (root/d).mkdir()
        db=Database(root/'db.sqlite'); db.init(); q=Downloader(db,TG(),root)
        item={'channel_id':1,'message_id':2,'channel_title':'频道','file_name':'../safe.mp4','size':123}
        a,dup=q.enqueue(item); b,dup2=q.enqueue(item)
        assert a==b and not dup and dup2
        assert db.one('select file_name from downloads where id=?',(a,))['file_name']=='safe.mp4'
        assert 'telegram_message_id' in {x['name'] for x in db.all('pragma table_info(outbox)')}
        db.close()

def test_restart_recovers():
    with tempfile.TemporaryDirectory() as td:
        db=Database(Path(td)/'db.sqlite'); db.init(); t='2020'
        db.execute("insert into downloads(channel_id,message_id,file_name,status,created_at,updated_at) values(1,1,'a','downloading',?,?)",(t,t))
        db2=Database(Path(td)/'db.sqlite'); db2.init()
        assert db2.one('select status from downloads')['status']=='downloading'
        db2.recover_interrupted()
        assert db2.one('select status from downloads')['status']=='queued'
        db.close(); db2.close()

def test_concurrent_workers_claim_only_once(tmp_path):
    db=Database(tmp_path/'db.sqlite'); db.init(); t='2020'
    cur=db.execute("insert into downloads(channel_id,message_id,file_name,status,created_at,updated_at) values(1,9,'a','queued',?,?)",(t,t)); job_id=cur.lastrowid
    barrier=threading.Barrier(2); results=[]
    def claim():
        barrier.wait(); results.append(db.execute("update downloads set status='downloading' where id=? and status='queued'",(job_id,)).rowcount); db.close()
    ts=[threading.Thread(target=claim) for _ in range(2)]
    for x in ts:x.start()
    for x in ts:x.join()
    assert sorted(results)==[0,1]
    db.close()

class FakeClient:
    def __init__(self,data,cancel_after_first=False): self.data=data; self.offsets=[]; self.cancel_after_first=cancel_after_first
    async def get_entity(self,channel_id): return channel_id
    async def get_messages(self,entity,ids):
        return SimpleNamespace(video=SimpleNamespace(size=len(self.data)),message='test',date=datetime.now(timezone.utc))
    async def iter_download(self,file,offset=0,**kwargs):
        self.offsets.append(offset); rest=self.data[offset:]
        if rest: yield rest[:3]
        if self.cancel_after_first: raise asyncio.CancelledError()
        if len(rest)>3: yield rest[3:]

class FakeTG:
    active_id=1
    def __init__(self,client): self.client=client
    async def get_client(self,account_id=None): return self.client

def make_download(tmp_path,data,cancel=False):
    root=tmp_path
    for name in ('media','temp','thumbnails'): (root/name).mkdir(exist_ok=True)
    db=Database(root/'db.sqlite'); db.init(); t='2020'
    cur=db.execute("insert into downloads(account_id,channel_id,message_id,channel_title,file_name,total_bytes,status,created_at,updated_at) values(1,1,7,'test','video.mp4',?,'downloading',?,?)",(len(data),t,t))
    client=FakeClient(data,cancel); dl=Downloader(db,FakeTG(client),root,min_free_gb=0); dl.probe=lambda p,j:{'duration':1,'width':1,'height':1,'thumb':''}
    return db,dl,client,cur.lastrowid

def test_resumes_from_existing_partial_file(tmp_path):
    data=b'abcdefghij'; db,dl,client,jid=make_download(tmp_path,data)
    (tmp_path/'temp'/f'{jid}.part').write_bytes(data[:4]); job=db.one('select * from downloads where id=?',(jid,))
    asyncio.run(dl.download(job))
    assert client.offsets==[4]
    assert next((tmp_path/'media').rglob('*_video.mp4')).read_bytes()==data
    assert db.one('select status from downloads where id=?',(jid,))['status']=='completed'; db.close()

def test_service_shutdown_keeps_partial_and_requeues(tmp_path):
    data=b'abcdefghij'; db,dl,client,jid=make_download(tmp_path,data,cancel=True); job=db.one('select * from downloads where id=?',(jid,))
    asyncio.run(dl.download(job))
    assert (tmp_path/'temp'/f'{jid}.part').read_bytes()==data[:3]
    row=db.one('select status,downloaded_bytes from downloads where id=?',(jid,)); assert row['status']=='queued' and row['downloaded_bytes']==3; db.close()

def test_manual_pause_keeps_partial_and_resume_requeues(tmp_path):
    data=b'abcdefghij'; db,dl,client,jid=make_download(tmp_path,data); part=tmp_path/'temp'/f'{jid}.part'; part.write_bytes(data[:4])
    dl.pause_requested.add(jid); job=db.one('select * from downloads where id=?',(jid,)); asyncio.run(dl.download(job))
    row=db.one('select status,downloaded_bytes from downloads where id=?',(jid,))
    assert row['status']=='paused' and row['downloaded_bytes']==4 and part.read_bytes()==data[:4]
    assert dl.resume(jid) and db.one('select status from downloads where id=?',(jid,))['status']=='queued'
    db.close()

def test_queued_pause_and_resume_are_persistent(tmp_path):
    data=b'abc'; db,dl,client,jid=make_download(tmp_path,data)
    db.execute("update downloads set status='queued' where id=?",(jid,))
    assert dl.pause(jid) and db.one('select status from downloads where id=?',(jid,))['status']=='paused'
    assert dl.resume(jid) and db.one('select status from downloads where id=?',(jid,))['status']=='queued'
    db.close()

def test_saved_messages_shortcut_targets_self():
    service=object.__new__(TelegramAccountService)
    class Client:
        async def get_me(self): return User(id=123456,is_self=True,first_name='Test')
    async def get_client(): return Client()
    service.get_client=get_client
    saved=asyncio.run(service.saved_messages())
    assert saved['peer_id']==123456 and saved['is_self'] and saved['title']=='收藏夹' and saved['can_send']

def test_self_entity_uses_telegram_me_peer():
    service=object.__new__(TelegramAccountService)
    class Client:
        def __init__(self): self.requested=[]
        async def get_me(self): return User(id=123456,is_self=True,first_name='Test')
        async def get_input_entity(self,value): self.requested.append(value); return 'self-peer'
        async def get_entity(self,value): raise AssertionError('收藏夹不应依赖普通会话缓存')
    client=Client()
    async def get_client(): return client
    service.get_client=get_client
    assert asyncio.run(service._entity(123456))=='self-peer'
    assert client.requested==['me']

def test_saved_messages_has_dedicated_desktop_and_mobile_entry():
    root=Path(__file__).parents[1]
    html=(root/'app/static/index.html').read_text(encoding='utf-8')
    js=(root/'app/static/app.js').read_text(encoding='utf-8')
    assert html.count('data-page="saved"')==2
    assert "saved:savedPage" in js
    assert "activePage==='saved'" in js
    assert "completed:'已发送'" in js
    assert 'class="ghost attach-button"' in js
    assert 'onclick="play(${local})"' in js

def test_uploaded_message_links_back_to_local_player():
    service=object.__new__(TelegramAccountService)
    class DB:
        def one(self,sql,args):
            assert args==(1,123,456)
            return {'media_id':9}
    service.db=DB(); service.account_id=1
    message=SimpleNamespace(id=456,out=True,sender=User(id=1,is_self=True,first_name='Test'),
        file=SimpleNamespace(name='video.mp4',size=1024,mime_type='video/mp4'),message='',date=datetime.now(timezone.utc),
        reply_to_msg_id=None,edit_date=None,buttons=None)
    result=asyncio.run(service._message_dict(message,123))
    assert result['media']['local_media_id']==9
