import asyncio
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

from app.db import Database, now
from app.media_tools import is_faststart, probe_media
from app.transcoder import Transcoder


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='ffmpeg is required')
def test_original_segments_keep_encoded_av_and_timing(tmp_path):
    """Exercise real AAC/H264 muxing, not just command construction."""
    import hashlib
    from app.media_tools import probe_streams
    db, worker, source = make_optimizer(tmp_path)
    try:
        subprocess.run(['ffmpeg', '-nostdin', '-y', '-v', 'error',
                        '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=24',
                        '-f', 'lavfi', '-i', 'sine=frequency=880:sample_rate=48000',
                        '-t', '9', '-c:v', 'libx264', '-g', '48', '-c:a', 'aac',
                        '-movflags', '+faststart', str(source)], check=True)
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        asyncio.run(worker._original(db.one('SELECT * FROM media'), source))
        row = db.one('SELECT * FROM media')
        assert row['original_hls_status'] == 'ready', row['original_hls_error']
        manifest = worker.original_directory(1) / 'index.m3u8'
        assert '#EXT-X-ENDLIST' in manifest.read_text()
        assert len(list(manifest.parent.glob('segment-*.ts'))) >= 2
        # Partial HTTP responses must already contain complete small fragments.
        assert (manifest.parent/'segment-00000.ts').read_bytes()[0] == 0x47
        assert (manifest.parent/'layout-v2').is_file()
        assert hashlib.sha256(source.read_bytes()).hexdigest() == before
        original = probe_streams(source)
        segmented = probe_streams(manifest)
        assert [s['codec_name'] for s in segmented] == ['h264', 'aac']
        def slices(path):
            # Compare encoded H264 slice payloads after normalizing AVCC/Annex B
            # and excluding container-inserted parameter sets and AUD packets.
            return subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-map','0:v:0',
                '-c','copy','-bsf:v','h264_mp4toannexb,filter_units=pass_types=1-5',
                '-f','streamhash','-hash','sha256','-']).split(b'=')[-1].strip()
        assert slices(source) == slices(manifest)
        # Decode the short sample to verify TS packetization does not change pixels.
        def frames(path):
            return subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-map','0:v:0','-f','framemd5','-']).splitlines()
        def pixels(path):
            return [line.split(b',')[-1].strip() for line in frames(path) if not line.startswith(b'#')]
        assert pixels(source) == pixels(manifest)
        # The first AAC priming packet can differ between MP4 and HLS; validate
        # the A/V relative origin and duration rather than ignoring that offset.
        def offset(streams):
            return float(streams[1]['start_time']) - float(streams[0]['start_time'])
        assert abs(offset(original) - offset(segmented)) < .050
        assert abs(probe_media(manifest)['duration'] - probe_media(source)['duration']) < .150
        worker.delete_variants(source, 1)
        assert source.is_file() and not manifest.parent.exists()
    finally:
        db.close()


def test_original_low_disk_keeps_source_and_no_partial_cache(tmp_path, monkeypatch):
    db, worker, source = make_optimizer(tmp_path)
    monkeypatch.setattr('app.transcoder.probe_streams', lambda _: [{'codec_type': 'video', 'codec_name': 'h264'}])
    monkeypatch.setattr('app.transcoder.shutil.disk_usage', lambda _: SimpleNamespace(free=0))
    try:
        asyncio.run(worker._original(db.one('SELECT * FROM media'), source))
        assert db.one('SELECT original_hls_status FROM media')['original_hls_status'] == 'failed'
        assert source.read_bytes() == b'original-video'
        assert not worker.original_directory(1).exists()
    finally:
        db.close()


def test_original_cache_upgrade_requeues_without_touching_source(tmp_path):
    db, worker, source = make_optimizer(tmp_path)
    async def check():
        db.execute("UPDATE media SET faststart=1,original_hls_status='ready'")
        await worker.start()
        assert db.one('SELECT original_hls_status FROM media')['original_hls_status']=='pending'
        await worker.stop()
    try:
        asyncio.run(check())
        assert source.read_bytes()==b'original-video'
    finally:
        db.close()


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='ffmpeg is required')
def test_hevc_keeps_muxed_fmp4_compatibility(tmp_path):
    from app.media_tools import probe_streams
    db, worker, source = make_optimizer(tmp_path)
    try:
        subprocess.run(['ffmpeg','-nostdin','-y','-v','error','-f','lavfi','-i',
            'testsrc2=size=160x90:rate=12','-f','lavfi','-i','sine=sample_rate=48000',
            '-t','2','-c:v','libx265','-preset','ultrafast','-x265-params',
            'pools=1:frame-threads=1:log-level=error','-tag:v','hvc1','-c:a','aac',str(source)],
            check=True,capture_output=True)
        asyncio.run(worker._original(db.one('SELECT * FROM media'), source))
        row=db.one('SELECT * FROM media')
        assert row['original_hls_status']=='ready',row['original_hls_error']
        root=worker.original_directory(1)
        assert (root/'init.mp4').is_file() and list(root.glob('*.m4s'))
        assert [s['codec_name'] for s in probe_streams(root/'index.m3u8')]==['hevc','aac']
    finally:
        db.close()


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
