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
from pathlib import Path

from .db import now
from .media_tools import (
    is_faststart,
    probe_media,
    remux_faststart,
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
        if self.proc and self.proc.returncode is None:
            try:
                self.proc.terminate()
            except ProcessLookupError:
                pass
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

    def enqueue_faststart(self, media_id: int):
        self.db.execute("UPDATE media SET faststart=0 WHERE id=?", (media_id,))

    def enqueue_smooth(self, media_id: int):
        row = self.db.one("SELECT smooth_status FROM media WHERE id=?", (media_id,))
        if not row or row["smooth_status"] in ("ready", "processing"):
            return
        self.db.execute(
            "UPDATE media SET smooth_status='queued', smooth_error='', smooth_progress=0 WHERE id=?",
            (media_id,),
        )

    def cancel_smooth(self, media_id: int):
        self.cancelled.add(int(media_id))
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
        if int(row.get("faststart") or 0) == 0:
            await self._faststart(row, path)
            row = self.db.one("SELECT * FROM media WHERE id=?", (media_id,))
            if not row:
                return
        if row.get("smooth_status") == "queued":
            await self._smooth(row, Path(row["file_path"]))
        self.current_id = None

    async def _faststart(self, row, path: Path):
        media_id = int(row["id"])
        if path.suffix.lower() != ".mp4" or is_faststart(path):
            self.db.execute("UPDATE media SET faststart=1 WHERE id=?", (media_id,))
            return
        self.db.execute("UPDATE media SET faststart=-1 WHERE id=?", (media_id,))
        temp = safe_variant_path(path, ".faststart.tmp.mp4")
        try:
            await asyncio.to_thread(remux_faststart, path, temp)
            os.replace(temp, path)
            info = await asyncio.to_thread(probe_media, path)
            self.db.execute(
                "UPDATE media SET faststart=1, size=?, duration=COALESCE(NULLIF(duration,0),?), "
                "width=COALESCE(NULLIF(width,0),?), height=COALESCE(NULLIF(height,0),?) WHERE id=?",
                (path.stat().st_size, info["duration"], info["width"], info["height"], media_id),
            )
            log.info("faststart 完成 id=%s size=%s", media_id, path.stat().st_size)
        except Exception as exc:
            temp.unlink(missing_ok=True)
            log.warning("faststart 失败 id=%s %s", media_id, exc)
            self.db.execute("UPDATE media SET faststart=2 WHERE id=?", (media_id,))

    async def _smooth(self, row, path: Path):
        media_id = int(row["id"])
        duration = float(row.get("duration") or 0)
        if duration <= 0:
            duration = (await asyncio.to_thread(probe_media, path))["duration"]
        destination = safe_variant_path(path, ".smooth.mp4")
        temp = safe_variant_path(path, ".smooth.tmp.mp4")
        temp.unlink(missing_ok=True)
        self.db.execute(
            "UPDATE media SET smooth_status='processing', smooth_progress=0, smooth_error='' WHERE id=?",
            (media_id,),
        )
        log.info("开始生成流畅版 id=%s path=%s", media_id, path)
        try:
            self.proc = await asyncio.create_subprocess_exec(
                *smooth_command(path, temp),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            last_saved = -1.0
            assert self.proc.stdout is not None
            while True:
                line = await self.proc.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", "replace").strip()
                if text.startswith("out_time_us=") or text.startswith("out_time_ms="):
                    try:
                        seconds = int(text.split("=", 1)[1]) / 1_000_000
                    except ValueError:
                        continue
                    if duration > 0:
                        percent = max(0.0, min(99.0, seconds / duration * 100))
                        if percent - last_saved >= 1:
                            last_saved = percent
                            self.db.execute(
                                "UPDATE media SET smooth_progress=? WHERE id=?", (percent, media_id)
                            )
                if media_id in self.cancelled:
                    self.proc.terminate()
                    break
            await self.proc.wait()
            stderr = b""
            if self.proc.stderr is not None:
                try:
                    stderr = await asyncio.wait_for(self.proc.stderr.read(4000), timeout=2)
                except Exception:
                    stderr = b""
            if media_id in self.cancelled:
                temp.unlink(missing_ok=True)
                self.cancelled.discard(media_id)
                return
            if self.proc.returncode != 0 or not temp.is_file() or temp.stat().st_size <= 0:
                raise RuntimeError((stderr.decode("utf-8", "replace") or "ffmpeg 转码失败").strip()[:300])
            os.replace(temp, destination)
            size = destination.stat().st_size
            self.db.execute(
                "UPDATE media SET smooth_path=?, smooth_status='ready', smooth_progress=100, "
                "smooth_size=?, smooth_error='' WHERE id=?",
                (str(destination), size, media_id),
            )
            log.info("流畅版完成 id=%s size=%s", media_id, size)
        except Exception as exc:
            temp.unlink(missing_ok=True)
            log.warning("流畅版失败 id=%s %s", media_id, exc)
            self.db.execute(
                "UPDATE media SET smooth_status='failed', smooth_error=?, smooth_progress=0 WHERE id=?",
                (str(exc)[:300], media_id),
            )
        finally:
            self.proc = None

    def delete_variants(self, path: Path):
        remove_media_variants(Path(path))
