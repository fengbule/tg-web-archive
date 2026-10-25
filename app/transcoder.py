"""Single-worker media optimizer.

Three jobs are tracked per media row:

``faststart``
    0 = pending, -1 = running, 1 = ready, 2 = not applicable/failed.

``smooth_status``
    idle / queued / processing / ready / failed.

``original_hls_status``
    pending / preparing / ready / unsupported / failed.

The worker prepares fast-start and original A/V segments before the optional
smooth transcode. Both original paths retain the encoded picture quality.
"""

from __future__ import annotations

import asyncio
import logging
import json
import math
import os
import shutil
from pathlib import Path
from .enhancement import RECIPE, enhancement_command, validate_enhancement, video_stream

from .media_tools import (
    faststart_command,
    original_hls_command,
    probe_streams,
    is_faststart,
    probe_media,
    remove_media_variants,
    safe_variant_path,
    smooth_command,
)

log = logging.getLogger("tvm.transcoder")


class SmoothDeferred(Exception):
    """Release the optional encoder when a download becomes runnable."""


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
        self.enhanced_cancelled = set()

    async def start(self):
        # Recover interrupted work without losing the user-visible state.
        self.db.execute("UPDATE media SET faststart=0 WHERE faststart=-1")
        self.db.execute("UPDATE media SET original_hls_status='pending' WHERE original_hls_status='preparing'")
        self.db.execute("UPDATE media SET preview_status='pending' WHERE preview_status='preparing'")
        for row in self.db.all("SELECT id FROM media WHERE preview_status='ready'"):
            if not (self.preview_directory(row['id']) / 'index.json').is_file():
                self.db.execute("UPDATE media SET preview_status='pending' WHERE id=?", (row['id'],))
        for row in self.db.all("SELECT id FROM media WHERE original_hls_status='ready'"):
            if not (self.original_directory(row['id']) / 'layout-v2').is_file():
                self.db.execute("UPDATE media SET original_hls_status='pending' WHERE id=?", (row['id'],))
        self.db.execute(
            "UPDATE media SET smooth_status='queued', smooth_error='服务重启后自动继续生成' "
            "WHERE smooth_status='processing'"
        )
        if self.auto_smooth:
            self.db.execute(
                "UPDATE media SET smooth_status='queued' "
                "WHERE smooth_status='idle' AND mime LIKE 'video/%'"
            )
        self.db.execute("UPDATE media SET enhanced_status='queued',enhanced_progress=0,"
                        "enhanced_error='服务重启后重新生成' WHERE enhanced_status='processing'")
        for row in self.db.all("SELECT id,enhanced_path FROM media WHERE enhanced_status='ready'"):
            if not Path(row['enhanced_path']).is_file():
                self.db.execute("UPDATE media SET enhanced_status='idle',enhanced_path='',enhanced_size=0,"
                                "enhanced_progress=0,enhanced_error='增强文件已移除，可重新生成' WHERE id=?", (row['id'],))
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

    def _is_cancelled(self):
        return self.current_id in (self.enhanced_cancelled if self.phase == 'enhanced' else self.cancelled)

    def enqueue_enhanced(self, media_id: int):
        with self.db.lock:
            if self.current_id == media_id and media_id in self.enhanced_cancelled:
                raise ValueError('正在停止增强任务，请稍后重试')
            row = self.db.one('SELECT enhanced_status,enhanced_path FROM media WHERE id=?', (media_id,))
            if not row:
                raise ValueError('视频不存在')
            if row['enhanced_status'] in ('queued', 'processing'):
                return
            if row['enhanced_status'] == 'ready' and Path(row['enhanced_path']).is_file():
                return
            self.enhanced_cancelled.discard(media_id)
            self.db.execute("UPDATE media SET enhanced_status='queued',enhanced_progress=0,enhanced_error='' WHERE id=?", (media_id,))

    def cancel_enhanced(self, media_id: int):
        with self.db.lock:
            if self.current_id == int(media_id) and self.phase == 'enhanced':
                self.enhanced_cancelled.add(int(media_id))
                proc = self.proc
                if proc and self.task:
                    def terminate():
                        if proc.returncode is None:
                            try: proc.terminate()
                            except ProcessLookupError: pass
                    self.task.get_loop().call_soon_threadsafe(terminate)
            self.db.execute("UPDATE media SET enhanced_status='idle',enhanced_progress=0,enhanced_error='已取消' WHERE id=?", (media_id,))

    async def worker(self):
        log.info("媒体优化 worker 已启动 auto_smooth=%s", self.auto_smooth)
        while not self.stopping:
            try:
                row = self.db.one(
                    "SELECT * FROM media "
                    "WHERE faststart=0 OR ((smooth_status='queued' OR enhanced_status='queued') AND NOT EXISTS (SELECT 1 FROM downloads WHERE status IN ('queued','downloading','pausing','retrying'))) OR original_hls_status='pending' OR preview_status='pending' "
                    "ORDER BY CASE WHEN faststart=0 OR original_hls_status='pending' THEN 0 WHEN preview_status='pending' THEN 1 ELSE 2 END, id LIMIT 1"
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
                "UPDATE media SET faststart=2, smooth_status='failed', smooth_error='源文件不存在', enhanced_status='failed',enhanced_error='源文件不存在', original_hls_status='failed', preview_status='failed' WHERE id=?",
                (media_id,),
            )
            return
        self.current_id = media_id
        try:
            if int(row.get("faststart") or 0) == 0:
                self.phase = 'faststart'
                await self._faststart(row, path)
            row = self.db.one("SELECT * FROM media WHERE id=?", (media_id,))
            if row and row.get('original_hls_status') == 'pending':
                self.phase = 'original'
                await self._original(row, Path(row['file_path']))
                row = self.db.one('SELECT * FROM media WHERE id=?', (media_id,))
            if row and row.get('preview_status') == 'pending':
                self.phase = 'preview'
                await self._preview(row, Path(row['file_path']))
                row = self.db.one('SELECT * FROM media WHERE id=?', (media_id,))
            if row and row.get("smooth_status") == "queued" and not self.db.one("SELECT 1 FROM downloads WHERE status IN ('queued','downloading','pausing','retrying') LIMIT 1"):
                self.phase = 'smooth'
                await self._smooth(row, Path(row["file_path"]))
            row = self.db.one("SELECT * FROM media WHERE id=?", (media_id,))
            if row and row.get('enhanced_status') == 'queued' and not self.db.one("SELECT 1 FROM downloads WHERE status IN ('queued','downloading','pausing','retrying') LIMIT 1"):
                self.phase = 'enhanced'
                await self._enhanced(row, Path(row['file_path']))
        finally:
            self.current_id = None
            self.phase = None
            self.cancelled.discard(media_id)
            self.enhanced_cancelled.discard(media_id)

    async def _run(self, command, progress=None, timeout=7200):
        """Drain both pipes and reap ffmpeg on shutdown, error or timeout."""
        proc = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        self.proc = proc
        if self._is_cancelled() and proc.returncode is None:
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
        if self.phase in ('smooth', 'enhanced'):
            async def yield_to_downloads():
                while proc.returncode is None:
                    if self.db.one("SELECT 1 FROM downloads WHERE status IN ('queued','downloading','pausing','retrying') LIMIT 1"):
                        raise SmoothDeferred()
                    await asyncio.sleep(.5)
            readers.append(asyncio.create_task(yield_to_downloads()))
        try:
            async with asyncio.timeout(timeout):
                await asyncio.gather(*readers)
                await proc.wait()
            if proc.returncode and not self._is_cancelled():
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
        except SmoothDeferred:
            if media_id not in self.cancelled:
                self.db.execute(
                    "UPDATE media SET smooth_status='queued',smooth_progress=0,"
                    "smooth_error='优先下载，空闲后重新生成流畅版' WHERE id=? AND smooth_status='processing'",
                    (media_id,),
                )
                log.info('流畅版退回队列，优先下载 id=%s', media_id)
        except Exception as exc:
            if media_id in self.cancelled: return
            log.warning("流畅版失败 id=%s %s", media_id, exc)
            self.db.execute(
                "UPDATE media SET smooth_status='failed', smooth_error=?, smooth_progress=0 WHERE id=?",
                (str(exc)[:300], media_id),
            )
        finally:
            temp.unlink(missing_ok=True)

    async def _enhanced(self, row, path):
        media_id = int(row['id'])
        destination = safe_variant_path(path, '.enhanced.mp4')
        temp = safe_variant_path(path, '.enhanced.tmp.mp4')
        try:
            with self.db.lock:
                if media_id in self.enhanced_cancelled or not self._source_unchanged(media_id, path): return
                if not self.db.execute("UPDATE media SET enhanced_status='processing',enhanced_progress=0,enhanced_error='' "
                                       "WHERE id=? AND enhanced_status='queued'", (media_id,)).rowcount: return
            source_stat = path.stat()
            streams = await asyncio.to_thread(probe_streams, path)
            video = video_stream(streams)
            info = await asyncio.to_thread(probe_media, path)
            duration = info['duration']
            if duration <= 0: raise ValueError('无法确定源视频时长，已保留原画')
            command = enhancement_command(path, temp, streams)
            reserve = max(2, float(os.getenv('MIN_FREE_GB', '2'))) * 1024**3
            # A high-quality re-encode can be larger than a heavily compressed source.
            estimate = max(source_stat.st_size * 2, duration * max(2_000_000,
                int(video.get('width', 0)) * int(video.get('height', 0)) * 4) / 8)
            if shutil.disk_usage(self.root).free < reserve + estimate:
                raise ValueError('磁盘剩余空间不足，暂不生成增强版')
            temp.unlink(missing_ok=True)
            last_saved = -1
            def progress(text):
                nonlocal last_saved
                if text.startswith('progress=') and shutil.disk_usage(self.root).free < reserve:
                    raise ValueError('磁盘已达到保护线，停止增强并保留原画')
                if text.startswith('out_time_us='):
                    try: percent = max(0, min(99, int(text.split('=', 1)[1]) / 1_000_000 / duration * 100))
                    except ValueError: return
                    if percent - last_saved >= 1:
                        last_saved = percent
                        self.db.execute("UPDATE media SET enhanced_progress=? WHERE id=? AND enhanced_status='processing'", (percent, media_id))
            if os.name == 'posix': command = ['nice', '-n', '10', *command]
            await self._run(command, progress, timeout=24 * 3600)
            if media_id in self.enhanced_cancelled: return
            output_streams = await asyncio.to_thread(probe_streams, temp)
            validate_enhancement(streams, output_streams)
            output_info = await asyncio.to_thread(probe_media, temp)
            if abs(output_info['duration'] - duration) > .25 or not is_faststart(temp):
                raise ValueError('增强文件完整性校验失败，已保留原画')
            with self.db.lock:
                if media_id in self.enhanced_cancelled or not self._source_unchanged(media_id, path): return
                latest = path.stat()
                if (latest.st_size, latest.st_mtime_ns) != (source_stat.st_size, source_stat.st_mtime_ns):
                    raise ValueError('源文件已变更，请重新生成增强版')
                state = self.db.one('SELECT enhanced_status FROM media WHERE id=?', (media_id,))
                if not state or state['enhanced_status'] != 'processing': return
                os.replace(temp, destination)
                self.db.execute("UPDATE media SET enhanced_path=?,enhanced_status='ready',enhanced_progress=100,"
                                "enhanced_size=?,enhanced_error='',enhanced_recipe=? WHERE id=?",
                                (str(destination), destination.stat().st_size, RECIPE, media_id))
            log.info('轻度增强完成 id=%s', media_id)
        except SmoothDeferred:
            if media_id not in self.enhanced_cancelled:
                self.db.execute("UPDATE media SET enhanced_status='queued',enhanced_progress=0,"
                                "enhanced_error='优先下载，空闲后重新生成增强版' WHERE id=? AND enhanced_status='processing'", (media_id,))
        except Exception as exc:
            if media_id not in self.enhanced_cancelled:
                log.warning('轻度增强失败 id=%s %s', media_id, exc)
                self.db.execute("UPDATE media SET enhanced_status='failed',enhanced_progress=0,enhanced_error=? WHERE id=?", (str(exc)[-300:], media_id))
        finally:
            temp.unlink(missing_ok=True)

    def original_directory(self, media_id):
        return self.root / 'media' / '.streams' / str(int(media_id))

    def preview_directory(self, media_id):
        return self.root / 'thumbnails' / 'seek-v1' / str(int(media_id))

    async def _preview(self, row, path):
        """Small contact sheets are separate from the original A/V stream."""
        media_id = int(row['id'])
        destination = self.preview_directory(media_id)
        temp = destination.with_name(destination.name + '.tmp')
        self.db.execute("UPDATE media SET preview_status='preparing' WHERE id=?", (media_id,))
        try:
            reserve = max(2, float(os.getenv('MIN_FREE_GB', '2'))) * 1024**3
            if shutil.disk_usage(self.root).free < reserve + 32 * 1024**2:
                raise RuntimeError('缩略图空间不足')
            duration = float(row.get('duration') or 0)
            if duration <= 0:
                duration = (await asyncio.to_thread(probe_media, path))['duration']
            # Bound CPU/storage even for very long recordings. Decode only key
            # frames; previews are approximate, the player seeks the exact time.
            interval = max(8, math.ceil(duration / 900))
            frames = max(1, math.floor(duration / interval))
            sheets = math.ceil(frames / 64)
            shutil.rmtree(temp, ignore_errors=True)
            temp.mkdir(parents=True)
            filters = (f'fps=1/{interval}:start_time=0:round=up,'
                       'scale=160:90:force_original_aspect_ratio=decrease,'
                       'pad=160:90:(ow-iw)/2:(oh-ih)/2,setsar=1,tile=8x8')
            command = ['ffmpeg','-nostdin','-y','-hide_banner','-loglevel','error',
                       '-threads','1','-skip_frame','nokey','-i',str(path),'-an',
                       '-vf',filters,'-frames:v',str(sheets),'-threads','1','-q:v','5',
                       '-progress','pipe:1','-nostats',str(temp/'sheet-%03d.jpg')]
            def progress(text):
                if text.startswith('progress=') and shutil.disk_usage(self.root).free < reserve:
                    raise RuntimeError('缩略图已到达磁盘保护线')
            await self._run(command, progress, timeout=3600)
            images = sorted(temp.glob('sheet-*.jpg'))
            if not images or any(p.stat().st_size == 0 for p in images):
                raise RuntimeError('缩略图生成失败')
            # Conservative tail clamp avoids selecting empty cells in a partial
            # sheet. The fps filter holds the latest decoded key frame.
            frames = min(frames, len(images) * 64)
            (temp/'index.json').write_text(json.dumps({'interval':interval,'frames':frames,
                'width':160,'height':90,'columns':8,'rows':8,'sheets':[p.name for p in images]}))
            if not self._source_unchanged(media_id, path):
                return
            shutil.rmtree(destination, ignore_errors=True)
            os.replace(temp, destination)
            self.db.execute("UPDATE media SET preview_status='ready' WHERE id=?", (media_id,))
        except Exception:
            log.warning('拖动预览生成失败 id=%s，保留时间预览', media_id)
            self.db.execute("UPDATE media SET preview_status='failed' WHERE id=?", (media_id,))
        finally:
            shutil.rmtree(temp, ignore_errors=True)

    async def _original(self, row, path):
        media_id = int(row['id'])
        destination = self.original_directory(media_id)
        temp = destination.with_name(destination.name + '.tmp')
        self.db.execute("UPDATE media SET original_hls_status='preparing',original_hls_error='' WHERE id=?", (media_id,))
        try:
            streams = await asyncio.to_thread(probe_streams, path)
            video = next((s for s in streams if s.get('codec_type') == 'video'), {})
            audio = next((s for s in streams if s.get('codec_type') == 'audio'), {})
            if video.get('codec_name') not in ('h264', 'hevc') or (audio and audio.get('codec_name') != 'aac'):
                self.db.execute("UPDATE media SET original_hls_status='unsupported',original_hls_error='原编码使用文件直连播放' WHERE id=?", (media_id,))
                return
            reserve = max(2, float(os.getenv('MIN_FREE_GB', '2'))) * 1024**3
            if shutil.disk_usage(self.root).free < reserve + path.stat().st_size * 1.05:
                raise RuntimeError('空间不足，继续使用原画文件直连')
            shutil.rmtree(temp, ignore_errors=True)
            temp.mkdir(parents=True, mode=0o755)
            def progress(text):
                if text.startswith('progress=') and shutil.disk_usage(self.root).free < reserve:
                    raise RuntimeError('已到达磁盘保护线，继续使用原画文件直连')
            await self._run(original_hls_command(path, temp, hevc=video['codec_name']=='hevc'), progress)
            manifest = temp / 'index.m3u8'
            if not manifest.is_file() or '#EXT-X-ENDLIST' not in manifest.read_text():
                raise RuntimeError('原画分片未完整生成')
            (temp / 'layout-v2').write_text('progressive-ts-h264-fmp4-hevc\n')
            if not self._source_unchanged(media_id, path): return
            # Publish the complete cache atomically; downloads keep the source.
            shutil.rmtree(destination, ignore_errors=True)
            os.replace(temp, destination)
            self.db.execute("UPDATE media SET original_hls_status='ready',original_hls_error='' WHERE id=?", (media_id,))
        except Exception as exc:
            log.warning('原画分片失败 id=%s %s', media_id, exc)
            self.db.execute("UPDATE media SET original_hls_status='failed',original_hls_error=? WHERE id=?", (str(exc)[-300:], media_id))
        finally:
            shutil.rmtree(temp, ignore_errors=True)

    def delete_variants(self, path: Path, media_id=None):
        remove_media_variants(Path(path))
        if media_id is not None:
            directory = self.original_directory(media_id)
            shutil.rmtree(directory, ignore_errors=True)
            shutil.rmtree(directory.with_name(directory.name + '.tmp'), ignore_errors=True)
            preview = self.preview_directory(media_id)
            shutil.rmtree(preview, ignore_errors=True)
            shutil.rmtree(preview.with_name(preview.name + '.tmp'), ignore_errors=True)
