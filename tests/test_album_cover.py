import asyncio,json
from pathlib import Path
from types import SimpleNamespace as NS
from cryptography.fernet import Fernet
from PIL import Image
from telethon.tl.types import PhotoSize
from app.db import Database,now
from app.telegram_service import TelegramManager


def test_album_photo_replaces_old_document_cover_and_preserves_video(tmp_path):
    db=Database(tmp_path/'db');db.init();svc=TelegramManager(tmp_path,tmp_path/'thumbs',db,Fernet(Fernet.generate_key())).service()
    old=tmp_path/'thumbs/source-v2/1/10/20.jpg';old.parent.mkdir(parents=True);Image.new('RGB',(30,20),'black').save(old)
    old.with_suffix('.source').write_text('telegram-thumbnail')
    video=tmp_path/'a.mp4';video.write_bytes(b'unchanged-original')
    db.execute('INSERT INTO media(channel_id,message_id,channel_title,file_name,file_path,thumb_path,size,downloaded_at) VALUES(10,20,\'Test\',\'a.mp4\',?,?,18,?)',(str(video),str(old),now()))
    photo=NS(sizes=[PhotoSize('x',1280,720,100)])
    poster=NS(id=19,grouped_id=900,photo=photo)
    other=NS(id=18,grouped_id=901,photo=NS(sizes=[PhotoSize('x',1280,720,100)]))
    msg=NS(id=20,grouped_id=900,video=NS(thumbs=[PhotoSize('s',160,90,10)]),media=NS(video_cover=None))
    calls=[]
    class Client:
        async def get_entity(self,cid):return cid
        async def get_messages(self,entity,ids):return [other,poster,msg] if isinstance(ids,list) else msg
        async def download_media(self,source,file,thumb):
            assert source is photo;calls.append(source);Image.new('RGB',(128,72),'green').save(file,format='JPEG');return file
    async def get_client():return Client()
    svc.get_client=get_client
    try:
        path=asyncio.run(svc.thumbnail(10,20));assert 'source-v3' in str(path)
        assert svc.thumbnail_origin(path)=='telegram-album'
        assert json.loads(path.with_suffix('.json').read_text())==dict(origin='telegram-album',source_message_id=19,grouped_id=900)
        assert db.one('SELECT thumb_path FROM media')['thumb_path']==str(path)
        assert old.is_file() and video.read_bytes()==b'unchanged-original'
        assert asyncio.run(svc.thumbnail(10,20))==path and len(calls)==1
    finally:db.close()


def test_nearby_photo_in_another_album_is_not_used(tmp_path):
    db=Database(tmp_path/'db');db.init();svc=TelegramManager(tmp_path,tmp_path/'thumbs',db,Fernet(Fernet.generate_key())).service()
    doc=NS(thumbs=[PhotoSize('s',160,90,10)])
    msg=NS(id=20,grouped_id=900,video=doc,media=NS(video_cover=None))
    class Client:
        async def get_entity(self,cid):return cid
        async def get_messages(self,entity,ids):return [NS(id=19,grouped_id=901,photo=NS(sizes=[]))] if isinstance(ids,list) else msg
        async def download_media(self,source,file,thumb):
            assert source is doc;Image.new('RGB',(16,9),'black').save(file,format='JPEG');return file
    async def get_client():return Client()
    svc.get_client=get_client
    try:assert svc.thumbnail_origin(asyncio.run(svc.thumbnail(10,20)))=='telegram-thumbnail'
    finally:db.close()


def test_custom_cover_still_wins_over_album_photo(tmp_path):
    db=Database(tmp_path/'db');db.init();svc=TelegramManager(tmp_path,tmp_path/'thumbs',db,Fernet(Fernet.generate_key())).service()
    custom=NS(sizes=[PhotoSize('x',1280,720,100)])
    msg=NS(id=20,grouped_id=900,video=NS(thumbs=[]),media=NS(video_cover=custom))
    class Client:
        async def get_entity(self,cid):return cid
        async def get_messages(self,entity,ids):return [NS(id=19,grouped_id=900,photo=NS(sizes=[PhotoSize('x',1280,720,100)]))] if isinstance(ids,list) else msg
        async def download_media(self,source,file,thumb):
            assert source is custom;Image.new('RGB',(128,72),'green').save(file,format='JPEG');return file
    async def get_client():return Client()
    svc.get_client=get_client
    try:assert svc.thumbnail_origin(asyncio.run(svc.thumbnail(10,20)))=='telegram-custom'
    finally:db.close()
