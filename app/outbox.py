import asyncio
import logging
import time
from pathlib import Path

from .db import now

log = logging.getLogger('tvm.outbox')


class UploadCancelled(Exception):
    pass


class OutboxSender:
    """Persistent, single-worker Telegram media sender.

    The database record survives a restart. Telegram uploads themselves cannot be
    resumed byte-for-byte, but the local media is never removed and the job will
    be safely retried after a service restart.
    """

    def __init__(self, db, tg, root: Path):
        self.db = db
        self.tg = tg
        self.root = root.resolve()
        self.worker_task = None
        self.stopping = False
        self.cancelled = set()

    async def start(self):
        self.worker_task = asyncio.create_task(self.worker())

    async def stop(self):
        self.stopping = True
        if self.worker_task:
            self.worker_task.cancel()
            await asyncio.gather(self.worker_task, return_exceptions=True)

    def enqueue(self, account_id: int, peer_id: int, media_id: int, caption: str = ''):
        media = self.db.one('SELECT id,size FROM media WHERE id=?', (media_id,))
        if not media:
            raise ValueError('媒体库文件不存在')
        t = now()
        cur = self.db.execute(
            """INSERT INTO outbox(account_id,peer_id,media_id,caption,status,total_bytes,created_at,updated_at)
               VALUES(?,?,?,?,'queued',?,?,?)""",
            (account_id, peer_id, media_id, caption[:1024], int(media['size']), t, t),
        )
        return cur.lastrowid

    def cancel(self, job_id: int):
        self.cancelled.add(job_id)
        changed = self.db.execute(
            "UPDATE outbox SET status='cancelled',error='已取消',updated_at=? WHERE id=? AND status='queued'",
            (now(), job_id),
        ).rowcount
        if changed:
            self.cancelled.discard(job_id)
        return bool(changed or self.db.one('SELECT 1 x FROM outbox WHERE id=?', (job_id,)))

    async def worker(self):
        while not self.stopping:
            job = self.db.one("SELECT * FROM outbox WHERE status='queued' ORDER BY id LIMIT 1")
            if not job:
                await asyncio.sleep(1)
                continue
            claimed = self.db.execute(
                "UPDATE outbox SET status='uploading',error='',updated_at=? WHERE id=? AND status='queued'",
                (now(), job['id']),
            ).rowcount
            if not claimed:
                await asyncio.sleep(.1)
                continue
            try:
                await self.send(job)
            except asyncio.CancelledError:
                self.db.execute(
                    "UPDATE outbox SET status='queued',error='服务重启后自动继续发送',updated_at=? WHERE id=?",
                    (now(), job['id']),
                )
                raise
            except UploadCancelled:
                self.cancelled.discard(job['id'])
                self.db.execute(
                    "UPDATE outbox SET status='cancelled',error='已取消',updated_at=? WHERE id=?",
                    (now(), job['id']),
                )
            except Exception as exc:
                log.exception('媒体发送失败 id=%s', job['id'])
                message = str(exc)
                if '内容保护' not in message:
                    message = '发送失败，请检查 Telegram 网络和会话权限后重试'
                self.db.execute(
                    "UPDATE outbox SET status='failed',error=?,updated_at=? WHERE id=?",
                    (message, now(), job['id']),
                )
            await asyncio.sleep(.2)

    async def send(self, job):
        media = self.db.one('SELECT * FROM media WHERE id=?', (job['media_id'],))
        if not media:
            raise ValueError('媒体库文件不存在')
        path = Path(media['file_path']).resolve()
        if self.root not in path.parents or not path.is_file():
            raise ValueError('媒体库文件不存在')
        if await self.tg.source_is_protected(int(media.get('account_id') or 1), media):
            raise ValueError('该来源启用了 Telegram 内容保护，不能通过本系统重新发送')
        last = 0.0

        async def progress(current, total):
            nonlocal last
            if job['id'] in self.cancelled:
                raise UploadCancelled()
            stamp = time.monotonic()
            if stamp - last >= .8 or current == total:
                self.db.execute(
                    'UPDATE outbox SET uploaded_bytes=?,total_bytes=?,updated_at=? WHERE id=?',
                    (int(current), int(total), now(), job['id']),
                )
                last = stamp

        sent = await self.tg.send_file(
            int(job['account_id']), int(job['peer_id']), path,
            caption=job['caption'], progress_callback=progress,
        )
        if isinstance(sent,(list,tuple)):
            sent=sent[0] if sent else None
        telegram_message_id=int(getattr(sent,'id',0) or 0) or None
        self.db.execute(
            "UPDATE outbox SET status='completed',uploaded_bytes=total_bytes,error='',telegram_message_id=?,updated_at=? WHERE id=?",
            (telegram_message_id,now(),job['id']),
        )
