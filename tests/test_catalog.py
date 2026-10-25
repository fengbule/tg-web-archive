import asyncio
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace
from cryptography.fernet import Fernet
from telethon.tl.types import InputMessagesFilterVideo,PhotoSize,VideoSize
from PIL import Image
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
                yield SimpleNamespace(id=mid,grouped_id=900 if mid==8 else None,video=SimpleNamespace(attributes=[],size=123,thumbs=[] if mid==8 else [object()]),message='',date=datetime.now(timezone.utc))
        async def download_media(self,*args,**kwargs):raise AssertionError('local cover should not call Telegram')
    async def get_client():return Client()
    svc.get_client=get_client
    try:
        result=asyncio.run(svc.videos(10,limit=2));assert result['next_offset_id']==8
        assert result['account_id']==1
        a,b=result['items'];assert a['downloaded'] and a['local_media_id'] and a['local_thumbnail']
        assert b['download_status']=='downloading' and b['download_progress']==50 and not b['downloaded']
        assert b['has_thumbnail'],'an album poster must be requested even without a document thumbnail'
        assert asyncio.run(svc.thumbnail(10,9))==thumb
        result=asyncio.run(svc.videos(10,limit=24));assert result['next_offset_id'] is None
        source.unlink();assert not asyncio.run(svc.videos(10))['items'][0]['downloaded']
    finally:db.close()

def test_concurrent_cover_requests_share_one_fetch_and_release_locks(tmp_path):
    db=Database(tmp_path/'db');db.init();tg=TelegramManager(tmp_path,tmp_path/'thumbs',db,Fernet(Fernet.generate_key()));svc=tg.service()
    class Client:
        calls=0
        async def get_entity(self,channel):return channel
        async def get_messages(self,entity,ids):return SimpleNamespace(video=SimpleNamespace(thumbs=[PhotoSize('m',320,180,100)]))
        async def download_media(self,doc,file,**kwargs):
            self.calls+=1;await asyncio.sleep(.01);Image.new('RGB',(32,18),'blue').save(file,format='JPEG');return file
    client=Client()
    async def get_client():return client
    svc.get_client=get_client
    async def run():
        paths=await asyncio.gather(*(svc.thumbnail(10,20) for _ in range(8)))
        assert len(set(paths))==1 and Image.open(paths[0]).format=='JPEG'
        assert client.calls==1 and not svc.thumbnail_locks
    try:asyncio.run(run())
    finally:db.close()

def test_custom_tg_cover_wins_over_frame_and_largest_static_is_selected(tmp_path):
    db=Database(tmp_path/'db');db.init();svc=TelegramManager(tmp_path,tmp_path/'thumbs',db,Fernet(Fernet.generate_key())).service()
    frame=tmp_path/'frame.jpg';Image.new('RGB',(10,10),'red').save(frame)
    db.execute('INSERT INTO media(channel_id,message_id,channel_title,file_name,file_path,thumb_path,size,downloaded_at) VALUES(10,20,\'Test\',\'a.mp4\',?,?,1,?)',(str(tmp_path/'a.mp4'),str(frame),now()))
    photo=SimpleNamespace(sizes=[PhotoSize('s',90,90,50),PhotoSize('x',1280,720,300)])
    msg=SimpleNamespace(video=SimpleNamespace(thumbs=[PhotoSize('m',320,180,100)],video_thumbs=[VideoSize('v',1280,720,1000)]),media=SimpleNamespace(video_cover=photo))
    calls=[]
    class Client:
        async def get_entity(self,id):return id
        async def get_messages(self,entity,ids):return msg
        async def download_media(self,source,file,thumb):
            calls.append((source,thumb));Image.new('RGB',(128,72),'green').save(file,format='JPEG');return file
    async def client():return Client()
    svc.get_client=client
    try:
        path=asyncio.run(svc.thumbnail(10,20));assert path!=frame and calls==[(photo,'x')]
        assert path.with_suffix('.source').read_text()=='telegram-custom'
        assert asyncio.run(svc.thumbnail(10,20))==path and len(calls)==1
        assert db.one('SELECT thumb_path FROM media')['thumb_path']==str(path)
        assert frame.is_file(),'the extracted fallback must remain available for rollback'
    finally:db.close()


def test_forced_cover_refresh_bypasses_old_message_and_image_cache(tmp_path):
    db=Database(tmp_path/'db');db.init();svc=TelegramManager(tmp_path,tmp_path/'thumbs',db,Fernet(Fernet.generate_key())).service()
    doc=SimpleNamespace(thumbs=[PhotoSize('m',320,180,100)])
    svc.video_messages[(10,20)]=SimpleNamespace(video=doc,media=SimpleNamespace(video_cover=None))
    new_photo=SimpleNamespace(sizes=[PhotoSize('x',1280,720,300)])
    class Client:
        calls=0;offline=False
        async def get_entity(self,id):return id
        async def get_messages(self,entity,ids):
            self.calls+=1
            if self.offline:raise ConnectionError('offline')
            return SimpleNamespace(video=doc,media=SimpleNamespace(video_cover=new_photo))
        async def download_media(self,source,file,thumb):
            Image.new('RGB',(128,72),'green' if source is new_photo else 'red').save(file,format='JPEG');return file
    client=Client()
    async def get_client():return client
    svc.get_client=get_client
    try:
        path=asyncio.run(svc.thumbnail(10,20));old=path.read_bytes()
        assert svc.thumbnail_origin(path)=='telegram-thumbnail' and client.calls==0
        assert asyncio.run(svc.thumbnail(10,20,refresh=True))==path
        assert path.read_bytes()!=old and svc.thumbnail_origin(path)=='telegram-custom' and client.calls==1
        import os,time
        os.utime(path,(time.time()-90000,time.time()-90000))
        asyncio.run(svc.thumbnail(10,20));assert client.calls==2,'daily revalidation must fetch the current message'
        latest=path.read_bytes();client.offline=True
        assert asyncio.run(svc.thumbnail(10,20,refresh=True))==path and path.read_bytes()==latest
    finally:db.close()

def test_invalid_custom_cover_uses_static_document_and_missing_source_keeps_frame(tmp_path):
    db=Database(tmp_path/'db');db.init();svc=TelegramManager(tmp_path,tmp_path/'thumbs',db,Fernet(Fernet.generate_key())).service()
    photo=SimpleNamespace(sizes=[PhotoSize('x',1280,720,300)])
    doc=SimpleNamespace(thumbs=[PhotoSize('m',320,180,100),VideoSize('v',1280,720,1000)])
    calls=[]
    class Client:
        async def get_entity(self,id):return id
        async def get_messages(self,entity,ids):return SimpleNamespace(video=doc,media=SimpleNamespace(video_cover=photo))
        async def download_media(self,source,file,thumb):
            calls.append(thumb)
            if source is photo:Path(file).write_bytes(b'not an image')
            else:Image.new('RGB',(32,18),'blue').save(file,format='JPEG')
            return file
    async def client():return Client()
    svc.get_client=client
    try:
        path=asyncio.run(svc.thumbnail(10,20));assert calls==['x','m']
        assert path.with_suffix('.source').read_text()=='telegram-thumbnail'
        frame=tmp_path/'frame.jpg';Image.new('RGB',(10,10),'red').save(frame)
        db.execute('INSERT INTO media(channel_id,message_id,channel_title,file_name,file_path,thumb_path,size,downloaded_at) VALUES(10,21,\'Test\',\'a.mp4\',?,?,1,?)',(str(tmp_path/'a.mp4'),str(frame),now()))
        async def offline():raise ConnectionError('offline')
        svc.get_client=offline
        assert asyncio.run(svc.thumbnail(10,21))==frame
        assert not svc.thumbnail_locks
    finally:db.close()
