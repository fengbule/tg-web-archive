import asyncio
import shutil
import subprocess
import threading
from types import SimpleNamespace

import pytest

from app.telegram_service import TelegramManager
from app.downloader import Downloader
from tests.test_core import make_download


def test_short_download_is_not_published(tmp_path):
    db, dl, client, jid = make_download(tmp_path, b'abcdefghij')

    async def truncated(*args, **kwargs):
        yield b'abc'

    client.iter_download = truncated
    try:
        with pytest.raises(ConnectionError):
            asyncio.run(dl.download(db.one('SELECT * FROM downloads WHERE id=?', (jid,))))
        assert (tmp_path / 'temp' / f'{jid}.part').read_bytes() == b'abc'
        assert not db.all('SELECT * FROM media')
        assert not list((tmp_path / 'media').rglob('*.mp4'))
    finally:
        db.close()


@pytest.mark.parametrize('action,status', [('cancel','cancelled'),('pause','paused')])
def test_control_during_media_probe_is_not_lost(tmp_path,action,status):
    db,dl,_,jid=make_download(tmp_path,b'abcdefghij')
    entered=threading.Event(); release=threading.Event()
    def probe(path,job_id):
        assert path.suffix=='.part'
        entered.set()
        assert release.wait(timeout=10)
        return {'duration':1,'width':1,'height':1,'thumb':''}
    dl.probe=probe
    async def check():
        task=asyncio.create_task(dl.download(db.one('SELECT * FROM downloads WHERE id=?',(jid,))))
        try:
            async def wait_for_probe():
                while not entered.is_set(): await asyncio.sleep(.001)
            await asyncio.wait_for(wait_for_probe(),timeout=5)
            assert getattr(dl,action)(jid)
        finally:
            release.set()
            await task
    try:
        asyncio.run(check())
        assert db.one('SELECT status FROM downloads WHERE id=?',(jid,))['status']==status
        assert not db.all('SELECT * FROM media')
        assert not list((tmp_path/'media').rglob('*.mp4'))
        partial=tmp_path/'temp'/f'{jid}.part'
        if action=='pause': assert partial.read_bytes()==b'abcdefghij'
        else: assert not partial.exists() and jid not in dl.cancelled
    finally:
        release.set(); db.close()


def test_shutdown_during_media_probe_retains_complete_partial(tmp_path):
    db,dl,_,jid=make_download(tmp_path,b'abcdefghij')
    entered=threading.Event(); release=threading.Event()
    def probe(path,job_id):
        entered.set(); assert release.wait(timeout=10)
        return {'duration':1,'width':1,'height':1,'thumb':''}
    dl.probe=probe
    async def check():
        task=asyncio.create_task(dl.download(db.one('SELECT * FROM downloads WHERE id=?',(jid,))))
        try:
            async def wait_for_probe():
                while not entered.is_set(): await asyncio.sleep(.001)
            await asyncio.wait_for(wait_for_probe(),timeout=5)
            task.cancel(); await task
        finally:
            release.set()
    try:
        asyncio.run(check())
        row=db.one('SELECT * FROM downloads WHERE id=?',(jid,))
        assert row['status']=='queued' and row['downloaded_bytes']==10
        assert (tmp_path/'temp'/f'{jid}.part').read_bytes()==b'abcdefghij'
        assert not db.all('SELECT * FROM media')
        assert not list((tmp_path/'media').rglob('*.mp4'))
    finally:
        release.set(); db.close()


def test_invalid_resume_and_retry_do_not_clear_pending_control(tmp_path):
    db,dl,_,jid=make_download(tmp_path,b'abc')
    try:
        assert dl.pause(jid)
        assert not dl.resume(jid) and not dl.retry(jid)
        assert jid in dl.pause_requested
        assert dl.cancel(jid)
        assert not dl.retry(jid) and jid in dl.cancelled
        asyncio.run(dl.download(db.one('SELECT * FROM downloads WHERE id=?',(jid,))))
        assert db.one('SELECT status FROM downloads WHERE id=?',(jid,))['status']=='cancelled'
    finally:
        db.close()


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'),reason='media tools unavailable')
def test_real_probe_accepts_partial_filename(tmp_path):
    db,dl,_,jid=make_download(tmp_path,b'abc')
    clip=tmp_path/'fixture.mp4'
    try:
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=160x90:r=2:d=2','-an','-c:v','mpeg4','-y',str(clip)],check=True,capture_output=True,timeout=15)
        partial=tmp_path/'temp'/f'{jid}.part'; partial.write_bytes(clip.read_bytes())
        meta=Downloader.probe(dl,partial,jid)
        assert meta['width']==160 and meta['height']==90 and meta['duration']>=1.9
        assert meta['thumb'] and (tmp_path/'thumbnails'/f'{jid}.jpg').is_file()
    finally:
        db.close()


@pytest.mark.parametrize('status', ['paused', 'failed', 'retrying', 'queued'])
def test_cancel_removes_partial_file_for_inactive_job(tmp_path, status):
    db, dl, _, jid = make_download(tmp_path, b'abcdefghij')
    part = tmp_path / 'temp' / f'{jid}.part'
    part.write_bytes(b'abcd')
    db.execute('UPDATE downloads SET status=?,temp_path=?,downloaded_bytes=4 WHERE id=?', (status, str(part), jid))
    try:
        assert dl.cancel(jid)
        row = db.one('SELECT * FROM downloads WHERE id=?', (jid,))
        assert row['status'] == 'cancelled'
        assert row['downloaded_bytes'] == 0 and row['temp_path'] == ''
        assert not part.exists()
        assert jid not in dl.cancelled
    finally:
        db.close()


def test_cancel_does_not_poison_completed_or_missing_job(tmp_path):
    db, dl, _, jid = make_download(tmp_path, b'abc')
    db.execute("UPDATE downloads SET status='completed' WHERE id=?", (jid,))
    try:
        assert not dl.cancel(jid)
        assert not dl.cancel(jid + 1)
        assert not dl.cancelled
    finally:
        db.close()


def test_resume_checks_only_remaining_disk_space(tmp_path, monkeypatch):
    db, dl, client, jid = make_download(tmp_path, b'abcdefghij')
    part = tmp_path / 'temp' / f'{jid}.part'
    part.write_bytes(b'abcdefgh')
    monkeypatch.setattr('app.downloader.shutil.disk_usage', lambda _: SimpleNamespace(free=3))
    try:
        asyncio.run(dl.download(db.one('SELECT * FROM downloads WHERE id=?', (jid,))))
        assert client.offsets == [8]
        assert db.one('SELECT status FROM downloads WHERE id=?', (jid,))['status'] == 'completed'
    finally:
        db.close()


@pytest.mark.parametrize('first_id', [1, 2])
def test_deleting_active_account_selects_remaining_account(tmp_path, first_id):
    db, _, _, _ = make_download(tmp_path, b'abc')
    if first_id==2:
        db.execute('DELETE FROM accounts')
        db.execute("INSERT INTO accounts(id,label,session_name,created_at) VALUES(2,'first','first','now')")
    remaining=first_id+1
    db.execute("INSERT INTO accounts(id,label,session_name,created_at) VALUES(?,'second','second','now')", (remaining,))
    manager = TelegramManager(tmp_path, tmp_path, db, None)
    manager.activate(first_id)
    # The integrated account manager correctly refuses removal during an active
    # download. Keep this regression focused on selecting the remaining account.
    db.execute("UPDATE downloads SET status='paused'")
    try:
        asyncio.run(manager.remove(first_id))
        assert manager.active_id == remaining
        assert manager.service().account_id == remaining
        assert db.one("SELECT value FROM config WHERE key='active_account_id'")['value'] == str(remaining)
    finally:
        db.close()
