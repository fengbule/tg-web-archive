import asyncio

import pytest

from tests.test_transcoder import make_optimizer


@pytest.mark.parametrize('status', ['queued', 'processing'])
def test_legacy_jobs_do_not_restart_or_run(tmp_path, monkeypatch, status):
    db, worker, source = make_optimizer(tmp_path)
    # Model an existing production DB: retired columns remain but have no worker.
    db.execute("ALTER TABLE media ADD COLUMN enhanced_status TEXT NOT NULL DEFAULT 'idle'")
    db.execute('UPDATE media SET enhanced_status=?,faststart=1,original_hls_status=\'ready\',preview_status=\'ready\'', (status,))
    for directory, filename in [(worker.original_directory(1), 'layout-v2'), (worker.preview_directory(1), 'index.json')]:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / filename).write_text('{}')
    processed = []
    async def record(row):
        processed.append(row['id'])
        await asyncio.sleep(0)
    monkeypatch.setattr(worker, 'process', record)
    async def check():
        await worker.start()
        try:
            await asyncio.sleep(.03)
            assert processed == []
            assert db.one('SELECT enhanced_status FROM media')['enhanced_status'] == status
        finally:
            await worker.stop()
    try:
        asyncio.run(check())
        assert source.read_bytes() == b'original-video'
        assert not list(tmp_path.glob('*.enhanced*.mp4'))
        assert not hasattr(worker, 'enqueue_enhanced')
    finally:
        db.close()
