import asyncio
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace
from cryptography.fernet import Fernet
from telethon.tl.types import InputMessagesFilterVideo
from app.db import Database,now
from app.telegram_service import TelegramManager

def test_video_filter_pagination_verified_local_and_job_states(tmp_path):
    db=Database(tmp_path/'db');db.init();tg=TelegramManager(tmp_path,tmp_path/'thumbs',db,Fernet(Fernet.generate_key()));svc=tg.service()
    source=tmp_path/'video.mp4';source.write_bytes(b'video');thumb=tmp_path/'cover.jpg';thumb.write_bytes(b'cover')
    db.execute('INSERT INTO media(account_id,channel_id,message_id,channel_title,file_name,file_path,thumb_path,size,downloaded_at) VALUES(1,10,9,?,?,?,?,1,?)',('Test','local.mp4',str(source),str(thumb),now()))
    db.execute('INSERT INTO downloads(account_id,channel_id,message_id,file_name,status,total_bytes,downloaded_bytes,created_at,updated_at) VALUES(1,10,8,?,?,?,?,?,?)',('queued.mp4','downloading',100,50,now(),now()))
    class Client:
        calls=0
        async def get_entity(self,channel):return SimpleNamespace(title='Test')
        async def iter_messages(self,entity,**kwargs):
            assert kwargs['filter'] is InputMessagesFilterVideo
            for mid in [9,8]:
                yield SimpleNamespace(id=mid,video=SimpleNamespace(attributes=[],size=123,thumbs=[object()]),message='',date=datetime.now(timezone.utc))
        async def download_media(self,*args,**kwargs):raise AssertionError('local cover should not call Telegram')
    async def get_client():return Client()
    svc.get_client=get_client
    try:
        result=asyncio.run(svc.videos(10,limit=2));assert result['next_offset_id']==8
        assert result['account_id']==1
        a,b=result['items'];assert a['downloaded'] and a['local_media_id'] and a['local_thumbnail']
        assert b['download_status']=='downloading' and b['download_progress']==50 and not b['downloaded']
        assert asyncio.run(svc.thumbnail(10,9))==thumb
        result=asyncio.run(svc.videos(10,limit=24));assert result['next_offset_id'] is None
        source.unlink();assert not asyncio.run(svc.videos(10))['items'][0]['downloaded']
    finally:db.close()

def test_concurrent_cover_requests_share_one_fetch_and_release_locks(tmp_path):
    db=Database(tmp_path/'db');db.init();tg=TelegramManager(tmp_path,tmp_path/'thumbs',db,Fernet(Fernet.generate_key()));svc=tg.service()
    class Client:
        calls=0
        async def get_entity(self,channel):return channel
        async def get_messages(self,entity,ids):return SimpleNamespace(video=SimpleNamespace(thumbs=[object()]))
        async def download_media(self,doc,file,**kwargs):
            self.calls+=1;await asyncio.sleep(.01);Path(file).write_bytes(b'JPEG');return file
    client=Client()
    async def get_client():return client
    svc.get_client=get_client
    async def run():
        paths=await asyncio.gather(*(svc.thumbnail(10,20) for _ in range(8)))
        assert len(set(paths))==1 and paths[0].read_bytes()==b'JPEG'
        assert client.calls==1 and not svc.thumbnail_locks
    try:asyncio.run(run())
    finally:db.close()
