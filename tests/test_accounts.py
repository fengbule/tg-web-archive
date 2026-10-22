import asyncio
import sqlite3
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from app.db import Database
from app.telegram_service import TelegramManager


@pytest.fixture
def manager(tmp_path):
    (tmp_path/'session').mkdir()
    db=Database(tmp_path/'app.db'); db.init()
    tg=TelegramManager(tmp_path/'session',tmp_path/'thumbs',db,Fernet(Fernet.generate_key()))
    tg.service().save_api(123456,'test-only-api-hash',test_mode=True)
    yield tg
    db.close()


class Client:
    def __init__(self,authorized=True,result=True):
        self.authorized=authorized; self.result=result; self.connected=False; self.calls=[]
    def is_connected(self): return self.connected
    async def connect(self): self.connected=True; self.calls.append('connect')
    async def disconnect(self): self.connected=False; self.calls.append('disconnect')
    async def is_user_authorized(self): return self.authorized
    async def get_me(self): return SimpleNamespace(first_name='Test',last_name='User',phone='1234567890')
    async def log_out(self):
        self.calls.append('logout')
        if isinstance(self.result,Exception): raise self.result
        return self.result


def test_account_creation_switch_rename_and_encrypted_config(manager):
    aid=manager.create_account('备用账号')
    manager.activate(aid); manager.rename_account(aid,'工作账号')
    second=manager.service(aid)
    assert second.credentials()==manager.service(1).credentials()
    assert second._cfg('api_test_mode')=='1'
    assert second._cfg('api_hash')!='test-only-api-hash'
    second.save_api(654321,'another-test-hash')
    assert manager.service(1).credentials()[0]==123456
    assert manager.active_id==aid
    assert second.session_name!=manager.service(1).session_name
    rows=asyncio.run(manager.list_accounts())
    assert rows[1]['label']=='工作账号' and rows[1]['active']
    assert all(x['authorized'] is False for x in rows)
    assert all('session_name' not in x and 'api_hash' not in x for x in rows)
    with pytest.raises(ValueError): manager.rename_account(aid,'  ')


def test_session_file_alone_is_not_a_logged_in_account(manager):
    aid=manager.create_account('备用')
    for account,authorized in ((1,True),(aid,False)):
        svc=manager.service(account); svc.client=Client(authorized)
        (manager.session_dir/(svc.session_name+'.session')).write_text('test session')
    rows=asyncio.run(manager.list_accounts())
    assert rows[0]['authorized'] is True and rows[0]['phone']=='***7890'
    assert rows[1]['session_exists'] and rows[1]['authorized'] is False


def test_logout_after_restart_reconnects_and_revokes_only_target(manager,monkeypatch):
    svc=manager.service(); client=Client(); constructed=[]
    def make_client(path,*args,**kwargs): constructed.append(path); return client
    monkeypatch.setattr('app.telegram_service.TelegramClient',make_client)
    target=manager.session_dir/(svc.session_name+'.session'); target.write_text('test session')
    sibling=manager.session_dir/(svc.session_name+'.session-other'); sibling.write_text('other account')
    asyncio.run(manager.logout(clear=True,account_id=1))
    assert constructed==[str(manager.session_dir/svc.session_name)]
    assert client.calls==['connect','logout','disconnect']
    assert not target.exists() and sibling.exists() and svc.client is None


@pytest.mark.parametrize('result',[False,ConnectionError('test network error')])
def test_logout_failure_keeps_saved_session_for_retry(manager,result):
    svc=manager.service(); svc.client=Client(result=result)
    target=manager.session_dir/(svc.session_name+'.session'); target.write_text('test session')
    with pytest.raises((RuntimeError,ConnectionError)): asyncio.run(manager.logout(clear=True,account_id=1))
    assert target.read_text()=='test session' and svc.client is None and not svc.ending_session


def test_logout_pauses_only_target_jobs_and_retains_media(manager):
    aid=manager.create_account('备用'); other=Client(); manager.service(1).client=other
    for account in (1,aid):
        manager.db.execute("INSERT INTO downloads(account_id,channel_id,message_id,file_name,status,created_at,updated_at) VALUES(?,?,1,'test','queued','t','t')",(account,account))
    mid=manager.db.execute("INSERT INTO media(channel_id,message_id,channel_title,file_name,file_path,size,downloaded_at) VALUES(1,1,'test','test','/test',1,'t')").lastrowid
    for account in (1,aid):
        manager.db.execute("INSERT INTO outbox(account_id,peer_id,media_id,status,created_at,updated_at) VALUES(?,1,?,'queued','t','t')",(account,mid))
    asyncio.run(manager.logout(clear=True,account_id=aid))
    assert manager.db.one('SELECT status FROM downloads WHERE account_id=?',(aid,))['status']=='paused'
    assert manager.db.one('SELECT status FROM outbox WHERE account_id=?',(aid,))['status']=='cancelled'
    assert manager.db.one('SELECT status FROM downloads WHERE account_id=1')['status']=='queued'
    assert manager.db.one('SELECT status FROM outbox WHERE account_id=1')['status']=='queued'
    assert manager.db.one('SELECT id FROM media')['id']==mid
    assert not other.calls and manager.active_id==1


def test_running_jobs_prevent_logout(manager):
    client=Client(); manager.service().client=client
    manager.db.execute("INSERT INTO downloads(channel_id,message_id,file_name,status,created_at,updated_at) VALUES(1,1,'test','downloading','t','t')")
    with pytest.raises(ValueError,match='正在运行'): asyncio.run(manager.logout(clear=True))
    assert not client.calls


def test_remove_active_first_account_selects_existing_fallback(manager):
    aid=manager.create_account('备用')
    asyncio.run(manager.remove(1))
    assert manager.active_id==aid and manager.service().account_id==aid
    assert manager.db.one("SELECT value FROM config WHERE key='active_account_id'")['value']==str(aid)
    assert not manager.db.one("SELECT key FROM config WHERE key IN ('api_id','api_hash','api_test_mode')")
    with pytest.raises(ValueError,match='至少保留'): asyncio.run(manager.remove(aid))


def test_legacy_database_migration_retains_ids_foreign_keys_and_account_scoping(tmp_path):
    path=tmp_path/'old.db'
    legacy=sqlite3.connect(path)
    legacy.executescript('''
      CREATE TABLE downloads(id INTEGER PRIMARY KEY AUTOINCREMENT,channel_id INTEGER NOT NULL,message_id INTEGER NOT NULL,
        channel_title TEXT NOT NULL DEFAULT '',file_name TEXT NOT NULL,total_bytes INTEGER NOT NULL DEFAULT 0,
        downloaded_bytes INTEGER NOT NULL DEFAULT 0,speed REAL NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'queued',
        retry_count INTEGER NOT NULL DEFAULT 0,error TEXT NOT NULL DEFAULT '',temp_path TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,updated_at TEXT NOT NULL,account_id INTEGER NOT NULL DEFAULT 1,UNIQUE(channel_id,message_id));
      CREATE TABLE media(id INTEGER PRIMARY KEY AUTOINCREMENT,download_id INTEGER UNIQUE,channel_id INTEGER NOT NULL,message_id INTEGER NOT NULL,
        channel_title TEXT NOT NULL,file_name TEXT NOT NULL,file_path TEXT NOT NULL UNIQUE,thumb_path TEXT NOT NULL DEFAULT '',
        size INTEGER NOT NULL,duration REAL NOT NULL DEFAULT 0,width INTEGER NOT NULL DEFAULT 0,height INTEGER NOT NULL DEFAULT 0,
        mime TEXT NOT NULL DEFAULT 'video/mp4',caption TEXT NOT NULL DEFAULT '',message_date TEXT NOT NULL DEFAULT '',downloaded_at TEXT NOT NULL,
        account_id INTEGER NOT NULL DEFAULT 1,FOREIGN KEY(download_id) REFERENCES downloads(id) ON DELETE SET NULL,UNIQUE(channel_id,message_id));
      INSERT INTO downloads(id,channel_id,message_id,file_name,created_at,updated_at) VALUES(7,123,456,'test','t','t');
      INSERT INTO media(id,download_id,channel_id,message_id,channel_title,file_name,file_path,size,downloaded_at) VALUES(9,7,123,456,'test','test','/test',1,'t');
      UPDATE sqlite_sequence SET seq=20 WHERE name='downloads';
    '''); legacy.commit(); legacy.close()
    db=Database(path); db.init()
    assert db.one('SELECT download_id FROM media WHERE id=9')['download_id']==7
    assert not db.all('PRAGMA foreign_key_check')
    other=db.execute("INSERT INTO downloads(account_id,channel_id,message_id,file_name,created_at,updated_at) VALUES(2,123,456,'other','t','t')").lastrowid
    assert other>20
    db.execute("INSERT INTO media(download_id,account_id,channel_id,message_id,channel_title,file_name,file_path,size,downloaded_at) VALUES(?,2,123,456,'test','test','/other',1,'t')",(other,))
    db.execute("INSERT INTO outbox(account_id,peer_id,media_id,created_at,updated_at) VALUES(1,1,9,'t','t')")
    db.init()  # A repeated startup must not rebuild or drop the new data.
    assert len(db.all('SELECT id FROM media'))==2
    db.execute('DELETE FROM downloads WHERE id=7')
    assert db.one('SELECT download_id FROM media WHERE id=9')['download_id'] is None
    db.execute('DELETE FROM media WHERE id=9')
    assert not db.all('SELECT id FROM outbox') and not db.all('PRAGMA foreign_key_check')
    db.close()
