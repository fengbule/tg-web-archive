import asyncio
import hashlib
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

from app.enhancement import enhancement_command, validate_enhancement
from app.media_tools import is_faststart, probe_streams
from tests.test_transcoder import make_optimizer


def test_reject_hdr_and_changed_timing():
    video = {'codec_type':'video','width':320,'height':180,'duration':'3','start_time':'0','nb_frames':'72'}
    audio = {'codec_type':'audio','duration':'3','start_time':'0'}
    with pytest.raises(ValueError, match='HDR'):
        enhancement_command('in', 'out', [{**video,'color_transfer':'smpte2084'}])
    with pytest.raises(ValueError, match='时间戳'):
        validate_enhancement([video,audio], [video,{**audio,'start_time':'.3'}])
    with pytest.raises(ValueError, match='帧数'):
        validate_enhancement([video], [{**video,'nb_frames':'71'}])
    with pytest.raises(ValueError, match='分辨率'):
        validate_enhancement([video], [{**video,'width':640}])


def test_queue_cancel_missing_variant_and_restart(tmp_path, monkeypatch):
    db, worker, source = make_optimizer(tmp_path)
    async def idle(): await asyncio.sleep(60)
    monkeypatch.setattr(worker, 'worker', idle)
    try:
        worker.enqueue_enhanced(1)
        db.execute('UPDATE media SET enhanced_progress=25')
        worker.enqueue_enhanced(1)
        assert db.one('SELECT enhanced_progress FROM media')['enhanced_progress'] == 25
        worker.cancel_enhanced(1)
        assert db.one('SELECT enhanced_status FROM media')['enhanced_status'] == 'idle'
        worker.enqueue_enhanced(1)
        db.execute("UPDATE media SET enhanced_status='processing'")
        async def restart():
            await worker.start()
            assert db.one('SELECT enhanced_status FROM media')['enhanced_status'] == 'queued'
            await worker.stop()
        asyncio.run(restart())
        db.execute("UPDATE media SET enhanced_status='ready',enhanced_path='missing.mp4'")
        asyncio.run(restart_missing(worker, db))
        assert source.read_bytes() == b'original-video'
    finally: db.close()


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='ffmpeg required')
@pytest.mark.parametrize('kind', ['rotated', 'variable-opus'])
def test_rotation_and_variable_rate_audio_are_not_broken(tmp_path, kind):
    db, worker, source = make_optimizer(tmp_path)
    base=tmp_path/'base.mp4'
    command=['ffmpeg','-nostdin','-y','-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=24',
             '-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','3']
    if kind=='rotated':
        subprocess.run(command+['-c:v','libx264','-c:a','aac',str(base)],check=True)
        subprocess.run(['ffmpeg','-nostdin','-y','-v','error','-i',str(base),'-c','copy','-metadata:s:v:0','rotate=90',str(source)],check=True)
    else:
        subprocess.run(command+['-vf',"select='not(mod(n,2))+not(mod(n,5))'",'-fps_mode','vfr',
                               '-c:v','libx264','-c:a','libopus','-f','matroska',str(source)],check=True)
    db.execute("UPDATE media SET faststart=1,original_hls_status='ready',preview_status='ready'")
    try:
        worker.enqueue_enhanced(1)
        asyncio.run(worker.process(db.one('SELECT * FROM media')))
        row=db.one('SELECT * FROM media')
        assert row['enhanced_status']=='ready',row['enhanced_error']
        result=probe_streams(source.with_name('original.enhanced.mp4'))
        if kind=='rotated': assert (result[0]['width'],result[0]['height'])==(180,320)
        else: assert next(s for s in result if s['codec_type']=='audio')['codec_name']=='aac'
    finally: db.close()


async def restart_missing(worker, db):
    worker.stopping = False
    await worker.start()
    assert db.one('SELECT enhanced_status FROM media')['enhanced_status'] == 'idle'
    await worker.stop()


def test_low_disk_preserves_source(tmp_path, monkeypatch):
    db, worker, source = make_optimizer(tmp_path)
    async def probe(_): return [{'codec_type':'video','width':320,'height':180}]
    monkeypatch.setattr('app.transcoder.probe_streams', lambda _: [{'codec_type':'video','width':320,'height':180}])
    monkeypatch.setattr('app.transcoder.probe_media', lambda _: {'duration':30})
    monkeypatch.setattr('app.transcoder.shutil.disk_usage', lambda _: SimpleNamespace(free=0))
    try:
        worker.enqueue_enhanced(1)
        asyncio.run(worker._enhanced(db.one('SELECT * FROM media'), source))
        row = db.one('SELECT * FROM media')
        assert row['enhanced_status']=='failed' and '磁盘' in row['enhanced_error']
        assert source.read_bytes()==b'original-video' and not list(tmp_path.glob('*.tmp.mp4'))
    finally: db.close()


@pytest.mark.parametrize('cancel', [False, True])
def test_running_enhancement_yields_and_cancellation_wins(tmp_path, monkeypatch, cancel):
    db, worker, source = make_optimizer(tmp_path)
    db.execute("UPDATE media SET faststart=1,original_hls_status='ready',preview_status='ready'")
    monkeypatch.setattr('app.transcoder.probe_streams', lambda _: [{'codec_type':'video','width':320,'height':180}])
    monkeypatch.setattr('app.transcoder.probe_media', lambda _: {'duration':30})
    monkeypatch.setattr('app.transcoder.enhancement_command', lambda src,dst,streams:
        [sys.executable,'-c',"import pathlib,sys,time;pathlib.Path(sys.argv[1]).write_bytes(b'partial');time.sleep(60)",str(dst)])
    async def check():
        worker.enqueue_enhanced(1)
        task=asyncio.create_task(worker.process(db.one('SELECT * FROM media')))
        worker.task=task
        try:
            async def started():
                while worker.proc is None: await asyncio.sleep(.001)
            await asyncio.wait_for(started(), 3)
            child=worker.proc
            if cancel: worker.cancel_enhanced(1)
            else:
                from app.db import now
                db.execute("INSERT INTO downloads(channel_id,message_id,file_name,status,created_at,updated_at) VALUES(9,9,'active','queued',?,?)",(now(),now()))
            await asyncio.wait_for(task, 5)
            assert child.returncode is not None
            assert db.one('SELECT enhanced_status FROM media')['enhanced_status']==('idle' if cancel else 'queued')
            assert not list(tmp_path.glob('*.tmp.mp4')) and source.read_bytes()==b'original-video'
        finally:
            task.cancel(); await asyncio.gather(task,return_exceptions=True)
    try: asyncio.run(check())
    finally: db.close()


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='ffmpeg required')
@pytest.mark.parametrize('audio', [True, False])
def test_real_enhancement_preserves_original_frames_audio_and_seek_points(tmp_path, audio):
    db, worker, source = make_optimizer(tmp_path)
    command=['ffmpeg','-nostdin','-y','-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=24']
    if audio: command += ['-f','lavfi','-i','sine=frequency=880:sample_rate=48000']
    subprocess.run(command+['-t','5','-c:v','libx264','-c:a','aac','-movflags','+faststart',str(source)],check=True)
    before=hashlib.sha256(source.read_bytes()).hexdigest()
    db.execute("UPDATE media SET faststart=1,original_hls_status='ready',preview_status='ready'")
    try:
        worker.enqueue_enhanced(1)
        asyncio.run(worker.process(db.one('SELECT * FROM media')))
        row=db.one('SELECT * FROM media')
        assert row['enhanced_status']=='ready',row['enhanced_error']
        destination=source.with_name('original.enhanced.mp4')
        assert destination.stat().st_size==row['enhanced_size'] and is_faststart(destination)
        assert row['enhanced_progress']==100
        assert hashlib.sha256(source.read_bytes()).hexdigest()==before
        original, enhanced=probe_streams(source),probe_streams(destination)
        validate_enhancement(original,enhanced)
        assert original[0]['nb_frames']==enhanced[0]['nb_frames']=='120'
        if audio:
            def audio_hash(p):return subprocess.check_output(['ffmpeg','-v','error','-i',str(p),'-map','0:a:0','-c','copy','-f','streamhash','-hash','sha256','-'])
            assert audio_hash(source)==audio_hash(destination)
        frames=subprocess.check_output(['ffprobe','-v','error','-select_streams','v','-skip_frame','nokey','-show_entries','frame=best_effort_timestamp_time','-of','csv=p=0',str(destination)],text=True)
        timestamps=[float(line.strip().strip(',')) for line in frames.splitlines() if line.strip().strip(',')]
        assert max(b-a for a,b in zip(timestamps,timestamps[1:]))<=2.05
        worker.delete_variants(source,1)
        assert not destination.exists() and source.is_file()
    finally: db.close()
