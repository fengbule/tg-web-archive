import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from telethon.errors import FloodWaitError,FloodPremiumWaitError
from app.db import Database
from app.downloader import Downloader


def setup(tmp_path):
    (tmp_path/'temp').mkdir()
    db=Database(tmp_path/'app.db');db.init()
    downloader=Downloader(db,SimpleNamespace(active_id=1),tmp_path,min_free_gb=0)
    ids=[downloader.enqueue({'account_id':account,'channel_id':1,'message_id':account,'file_name':'test.mp4','size':100})[0] for account in (1,2)]
    return db,downloader,ids


def test_wait_preserves_real_prefix_retry_budget_and_other_account(tmp_path,monkeypatch):
    import app.downloader as module
    clock=[1000.0];monkeypatch.setattr(module.time,'time',lambda:clock[0])
    db,downloader,ids=setup(tmp_path)
    try:
        job=db.one('select * from downloads where id=?',(ids[0],))
        db.execute("update downloads set retry_count=2,status='downloading' where id=?",(ids[0],))
        partial=tmp_path/'temp'/f'{ids[0]}.part';partial.write_bytes(b'preserved prefix')
        downloader.defer_for_rate_limit(job,120)
        row=db.one('select * from downloads where id=?',(ids[0],))
        assert row['status']=='queued' and row['downloaded_bytes']==len(partial.read_bytes()) and row['retry_count']==2
        assert downloader.ready_job()['id']==ids[1]
        downloader.pause(ids[1]);db.recover_interrupted()
        restarted=Downloader(db,SimpleNamespace(active_id=1),tmp_path,min_free_gb=0)
        assert restarted.ready_job() is None
        restarted.pause(ids[0]);assert restarted.resume(ids[0])
        assert restarted.ready_job() is None  # Manual resume does not bypass the server wait.
        clock[0]=1122.0
        assert restarted.ready_job()['id']==ids[0] and partial.read_bytes()==b'preserved prefix'
    finally:db.close()


@pytest.mark.parametrize('paused,cancelled',[(True,False),(False,True)])
def test_pause_or_cancel_during_rate_wait_keeps_user_choice(tmp_path,paused,cancelled):
    db,downloader,ids=setup(tmp_path)
    try:
        job=db.one('select * from downloads where id=?',(ids[0],));part=tmp_path/'temp'/f'{ids[0]}.part';part.write_bytes(b'prefix')
        if paused:downloader.pause_requested.add(ids[0])
        if cancelled:downloader.cancelled.add(ids[0])
        downloader.defer_for_rate_limit(job,30)
        state=db.one('select * from downloads where id=?',(ids[0],))
        assert state['status']==('paused' if paused else 'cancelled')
        assert part.exists()==paused
    finally:db.close()


@pytest.mark.parametrize('error',[FloodWaitError(None,capture=120),FloodPremiumWaitError(None,capture=120)])
def test_worker_handles_server_wait_without_normal_retry_failures(tmp_path,error):
    db,downloader,ids=setup(tmp_path);downloader.pause(ids[1])
    async def run():
        called=asyncio.Event()
        async def download(job):called.set();raise error
        downloader.download=download
        await downloader.start()
        try:
            await asyncio.wait_for(called.wait(),2)
            row=db.one('select * from downloads where id=?',(ids[0],))
            assert row['status']=='queued' and row['retry_count']==0
            assert downloader.ready_job() is None
        finally:await downloader.stop()
    try:asyncio.run(run())
    finally:db.close()
