import asyncio
from pathlib import Path
from types import SimpleNamespace
from app.cover_refresh import CoverRefresh


def test_refresh_is_singleton_and_reports_partial_results(tmp_path):
    class DB:
        def all(self,query):return [dict(account_id=1,channel_id=10,message_id=i) for i in range(3)]
    class TG:
        def service(self,aid):return self
        async def thumbnail(self,cid,mid,refresh):
            assert refresh is True
            if mid==2:raise ConnectionError('offline')
            path=tmp_path/f'{mid}.jpg';path.write_bytes(b'fixture')
            if mid==0:path.with_suffix('.source').write_text('telegram-custom')
            return path
    async def run():
        job=CoverRefresh(DB(),TG());assert job.start()['total']==3
        task=job.task;job.start();assert job.task is task
        await task
        assert job.state==dict(status='completed',total=3,done=3,original=1,updated=1,retained=0,fallback=1,unavailable=1)
    asyncio.run(run())


def test_refresh_shutdown_cancels_before_telegram_disconnect():
    class DB:
        def all(self,query):return [dict(account_id=1,channel_id=10,message_id=1)]
    class TG:
        def service(self,aid):return self
        async def thumbnail(self,*args,**kwargs):await asyncio.sleep(100)
    async def run():
        job=CoverRefresh(DB(),TG());job.start();await asyncio.sleep(0)
        await job.stop();assert job.state['status']=='interrupted' and job.task.done()
    asyncio.run(run())
