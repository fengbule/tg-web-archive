import asyncio
from types import SimpleNamespace

import pytest

from app.telegram_service import TelegramManager
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

    class Service:
        async def logout(self, clear=False):
            pass

    manager.services[first_id] = Service()
    try:
        asyncio.run(manager.remove(first_id))
        assert manager.active_id == remaining
        assert manager.service().account_id == remaining
        assert db.one("SELECT value FROM config WHERE key='active_account_id'")['value'] == str(remaining)
    finally:
        db.close()
