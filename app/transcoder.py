"""Single-worker media optimizer.

Two independent jobs are tracked per media row:

``faststart``
    0 = pending, -1 = running, 1 = ready, 2 = not applicable/failed.

``smooth_status``
    idle / queued / processing / ready / failed.

The worker always finishes a fast-start remux before a smooth transcode, so a
newly downloaded file becomes seekable even when the user never asks for the
low-bitrate variant.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from pathlib import Path

from .media_tools import (
    faststart_command,
    is_faststart,
    probe_media,
    remove_media_variants,
    safe_variant_path,
    smooth_command,
)

log = logging.getLogger("tvm.transcoder")


class Transcoder:
    def __init__(self, db, root: Path, auto_smooth: bool = False):
        self.db = db
        self.root = root
        self.auto_smooth = auto_smooth
        self.task = None
        self.proc = None
        self.current_id = None
        self.phase = None
        self.stopping = False
        self.cancelled = set()

    async def start(self):
        # Recover interrupted work without losing the user-visible state.
        self.db.execute("UPDATE media SET faststart=0 WHERE faststart=-1")
        self.db.execute(
            "UPDATE media SET smooth_status='queued', smooth_error='服务重启后自动继续生成' "
            "WHERE smooth_status='processing'"
        )
        if self.auto_smooth:
            self.db.execute(
                "UPDATE media SET smooth_status='queued' "
                "WHERE smooth_status='idle' AND mime LIKE 'video/%'"
            )
        self.task = asyncio.create_task(self.worker())

    async def stop(self):
        self.stopping = True
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

    def enqueue_faststart(self, media_id: int):
        self.db.execute("UPDATE media SET faststart=0 WHERE id=?", (media_id,))

    def enqueue_smooth(self, media_id: int):
        if self.current_id == media_id and media_id in self.cancelled:
            raise ValueError('正在结束上一次优化任务，请稍后重试')
        self.cancelled.discard(media_id)
        row = self.db.one("SELECT smooth_status FROM media WHERE id=?", (media_id,))
        if not row or row["smooth_status"] in ("ready", "processing"):
            return
        self.db.execute(
            "UPDATE media SET smooth_status='queued', smooth_error='', smooth_progress=0 WHERE id=?",
            (media_id,),
        )

    def cancel_smooth(self, media_id: int):
        if self.current_id == int(media_id) and self.phase == 'smooth':
            self.cancelled.add(int(media_id))
            proc = self.proc
            if proc and self.task:
                def terminate():
                    if proc.returncode is None:
                        try: proc.terminate()
                        except ProcessLookupError: pass
                self.task.get_loop().call_soon_threadsafe(terminate)
        self.db.execute(
            "UPDATE media SET smooth_status='idle', smooth_progress=0, smooth_error='已取消' WHERE id=?",
            (media_id,),
        )

    async def worker(self):
        log.info("媒体优化 worker 已启动 auto_smooth=%s", self.auto_smooth)
        while not self.stopping:
            try:
                row = self.db.one(
                    "SELECT * FROM media "
                    "WHERE faststart=0 OR smooth_status='queued' "
                    "ORDER BY CASE WHEN smooth_status='queued' THEN 0 ELSE 1 END, id LIMIT 1"
                )
                if not row:
                    await asyncio.sleep(2)
                    continue
                await self.process(row)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("媒体优化任务异常")
                await asyncio.sleep(2)

    async def process(self, row):
        media_id = int(row["id"])
        path = Path(row["file_path"])
        if not path.is_file():
            self.db.execute(
                "UPDATE media SET faststart=2, smooth_status='failed', smooth_error='源文件不存在' WHERE id=?",
                (media_id,),
            )
            return
        self.current_id = media_id
        try:
            if int(row.get("faststart") or 0) == 0:
                self.phase = 'faststart'
                await self._faststart(row, path)
            row = self.db.one("SELECT * FROM media WHERE id=?", (media_id,))
            if row and row.get("smooth_status") == "queued":
                self.phase = 'smooth'
                await self._smooth(row, Path(row["file_path"]))
        finally:
            self.current_id = None
            self.phase = None
            self.cancelled.discard(media_id)

    async def _run(self, command, progress=None, timeout=7200):
        """Drain both pipes and reap ffmpeg on shutdown, error or timeout."""
        proc = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        self.proc = proc
        if self.current_id in self.cancelled and proc.returncode is None:
            proc.terminate()
        tail = bytearray()

        async def drain_error():
            while chunk := await proc.stderr.read(8192):
                tail.extend(chunk)
                if len(tail) > 4000: del tail[:-4000]

        async def drain_progress():
            while line := await proc.stdout.readline():
                if progress: progress(line.decode('utf-8', 'replace').strip())

        readers = [asyncio.create_task(drain_error()), asyncio.create_task(drain_progress())]
        try:
            async with asyncio.timeout(timeout):
                await asyncio.gather(*readers)
                await proc.wait()
            if proc.returncode and self.current_id not in self.cancelled:
                raise RuntimeError((tail.decode('utf-8', 'replace') or 'ffmpeg 优化失败')[-300:])
        finally:
            if proc.returncode is None:
                try: proc.terminate()
                except ProcessLookupError: pass
                try: await asyncio.wait_for(proc.wait(), 5)
                except TimeoutError:
                    proc.kill()
                    await proc.wait()
            for reader in readers: reader.cancel()
            await asyncio.gather(*readers, return_exceptions=True)
            if self.proc is proc: self.proc = None

    def _source_unchanged(self, media_id, path):
        row = self.db.one('SELECT file_path FROM media WHERE id=?', (media_id,))
        return row and Path(row['file_path']) == path and path.is_file()

    async def _faststart(self, row, path: Path):
        media_id = int(row["id"])
        if path.suffix.lower() != ".mp4" or is_faststart(path):
            self.db.execute("UPDATE media SET faststart=1 WHERE id=?", (media_id,))
            return
        self.db.execute("UPDATE media SET faststart=-1 WHERE id=?", (media_id,))
        temp = safe_variant_path(path, ".faststart.tmp.mp4")
        try:
            reserve = max(2, float(os.getenv('MIN_FREE_GB', '2'))) * 1024**3
            if shutil.disk_usage(self.root).free < path.stat().st_size + reserve:
                raise RuntimeError('磁盘空间不足，保留原视频并跳过索引优化')
            await self._run(faststart_command(path, temp))
            info = await asyncio.to_thread(probe_media, temp)
            if not info['duration'] or not is_faststart(temp):
                raise RuntimeError('索引优化输出校验失败，保留原视频')
            if not self._source_unchanged(media_id, path): return
            os.replace(temp, path)
            self.db.execute(
                "UPDATE media SET faststart=1, size=?, duration=COALESCE(NULLIF(duration,0),?), "
                "width=COALESCE(NULLIF(width,0),?), height=COALESCE(NULLIF(height,0),?) WHERE id=?",
                (path.stat().st_size, info["duration"], info["width"], info["height"], media_id),
            )
            log.info("faststart 完成 id=%s size=%s", media_id, path.stat().st_size)
        except Exception as exc:
            log.warning("faststart 失败 id=%s %s", media_id, exc)
            self.db.execute("UPDATE media SET faststart=2 WHERE id=?", (media_id,))
        finally:
            temp.unlink(missing_ok=True)

    async def _smooth(self, row, path: Path):
        media_id = int(row["id"])
        duration = float(row.get("duration") or 0)
        if duration <= 0:
            duration = (await asyncio.to_thread(probe_media, path))["duration"]
        if media_id in self.cancelled or not self._source_unchanged(media_id, path): return
        destination = safe_variant_path(path, ".smooth.mp4")
        temp = safe_variant_path(path, ".smooth.tmp.mp4")
        free = shutil.disk_usage(self.root).free
        reserve = max(2, float(os.getenv('MIN_FREE_GB', '2'))) * 1024**3
        estimated = duration * (900_000 + 96_000) / 8 * 1.2 + 8 * 1024**2
        if free < reserve + estimated:
            self.db.execute(
                "UPDATE media SET smooth_status='failed', smooth_error='磁盘剩余空间不足，暂不生成流畅版', smooth_progress=0 WHERE id=?",
                (media_id,),
            )
            return
        temp.unlink(missing_ok=True)
        self.db.execute(
            "UPDATE media SET smooth_status='processing', smooth_progress=0, smooth_error='' WHERE id=?",
            (media_id,),
        )
        log.info("开始生成流畅版 id=%s path=%s", media_id, path)
        try:
            last_saved = -1.0
            def progress(text):
                nonlocal last_saved
                if text.startswith('progress=') and shutil.disk_usage(self.root).free < reserve:
                    raise RuntimeError('磁盘已达到保护线，停止生成流畅版并保留原视频')
                if text.startswith("out_time_us=") or text.startswith("out_time_ms="):
                    try:
                        seconds = int(text.split("=", 1)[1]) / 1_000_000
                    except ValueError:
                        return
                    if duration > 0:
                        percent = max(0.0, min(99.0, seconds / duration * 100))
                        if percent - last_saved >= 1:
                            last_saved = percent
                            self.db.execute(
                                "UPDATE media SET smooth_progress=? WHERE id=?", (percent, media_id)
                            )
            await self._run(smooth_command(path, temp), progress, timeout=24 * 3600)
            if media_id in self.cancelled:
                return
            if not temp.is_file() or temp.stat().st_size <= 0:
                raise RuntimeError('ffmpeg 输出为空')
            if not self._source_unchanged(media_id, path): return
            os.replace(temp, destination)
            size = destination.stat().st_size
            self.db.execute(
                "UPDATE media SET smooth_path=?, smooth_status='ready', smooth_progress=100, "
                "smooth_size=?, smooth_error='' WHERE id=?",
                (str(destination), size, media_id),
            )
            log.info("流畅版完成 id=%s size=%s", media_id, size)
        except Exception as exc:
            if media_id in self.cancelled: return
            log.warning("流畅版失败 id=%s %s", media_id, exc)
            self.db.execute(
                "UPDATE media SET smooth_status='failed', smooth_error=?, smooth_progress=0 WHERE id=?",
                (str(exc)[:300], media_id),
            )
        finally:
            temp.unlink(missing_ok=True)

    def delete_variants(self, path: Path):
        remove_media_variants(Path(path))
