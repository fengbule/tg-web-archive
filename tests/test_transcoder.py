import asyncio
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

from app.db import Database, now
from app.media_tools import is_faststart, probe_media
from app.transcoder import Transcoder


def make_optimizer(tmp_path):
    db = Database(tmp_path / 'app.db')
    db.init()
    source = tmp_path / 'original.mp4'
    source.write_bytes(b'original-video')
    db.execute("INSERT INTO media(channel_id,message_id,channel_title,file_name,file_path,size,downloaded_at) "
               "VALUES(1,1,'test','original.mp4',?,?,?)", (str(source), source.stat().st_size, now()))
    return db, Transcoder(db, tmp_path), source


def test_queued_cancel_can_be_started_again(tmp_path):
    db, worker, _ = make_optimizer(tmp_path)
    try:
        worker.enqueue_smooth(1)
        worker.cancel_smooth(1)
        worker.enqueue_smooth(1)
        assert db.one('SELECT smooth_status FROM media')['smooth_status'] == 'queued'
        assert 1 not in worker.cancelled
    finally:
        db.close()


def test_faststart_low_disk_keeps_original(tmp_path, monkeypatch):
    db, worker, source = make_optimizer(tmp_path)
    monkeypatch.setattr('app.transcoder.shutil.disk_usage', lambda _: SimpleNamespace(free=0))
    try:
        asyncio.run(worker.process(db.one('SELECT * FROM media')))
        assert source.read_bytes() == b'original-video'
        assert db.one('SELECT faststart FROM media')['faststart'] == 2
        assert not list(tmp_path.glob('*.tmp.mp4'))
        assert worker.current_id is None
    finally:
        db.close()


def test_optimizer_drains_large_stderr_without_hanging(tmp_path):
    worker = Transcoder(None, tmp_path)
    asyncio.run(worker._run([sys.executable, '-c', "import sys;sys.stderr.write('x'*300000);sys.stderr.flush()"], timeout=10))
    assert worker.proc is None


@pytest.mark.parametrize('timeout', [False, True])
def test_optimizer_reaps_process_on_cancel_or_timeout(tmp_path, timeout):
    async def check():
        worker = Transcoder(None, tmp_path)
        task = asyncio.create_task(worker._run(
            [sys.executable, '-c', 'import time;time.sleep(60)'], timeout=.2 if timeout else 30))
        while worker.proc is None:
            await asyncio.sleep(.001)
        child = worker.proc
        if timeout:
            with pytest.raises(TimeoutError): await task
        else:
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
        assert child.returncode is not None
        assert worker.proc is None
    asyncio.run(check())


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='ffmpeg is required')
def test_real_faststart_and_smooth_preserve_source_and_dimensions(tmp_path):
    db, worker, source = make_optimizer(tmp_path)
    try:
        subprocess.run(['ffmpeg', '-nostdin', '-y', '-v', 'error', '-f', 'lavfi', '-i',
                        'testsrc2=size=640x360:rate=24', '-t', '3', '-c:v', 'libx264', str(source)], check=True)
        assert not is_faststart(source)
        worker.enqueue_smooth(1)
        asyncio.run(worker.process(db.one('SELECT * FROM media')))
        row = db.one('SELECT * FROM media')
        assert row['faststart'] == 1 and is_faststart(source)
        assert row['smooth_status'] == 'ready', row['smooth_error']
        info = probe_media(source.with_name('original.smooth.mp4'))
        assert info['height'] == 360  # Do not upscale small videos to 480p.
        assert info['duration'] >= 2.9
        assert not list(tmp_path.glob('*.tmp.mp4'))
    finally:
        db.close()
