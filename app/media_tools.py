"""Media post-processing helpers: fast-start MP4 remux and low-bitrate variants.

The Telegram client writes the original file exactly as uploaded.  Many
recordings put the MP4 ``moov`` atom at the end of the file, which forces a
browser to read the tail of a multi-gigabyte file before playback can start.
Remuxing with ``-movflags +faststart`` moves the index to the front without
touching the audio/video bitstreams.
"""

from __future__ import annotations

import json
import os
import struct
import subprocess
from pathlib import Path

SMOOTH_HEIGHT = 480
SMOOTH_MAXRATE = "900k"
SMOOTH_AUDIO_BITRATE = "96k"


def iter_top_level_boxes(path: Path):
    """Yield ``(type, offset, size)`` for top-level ISO BMFF boxes."""
    file_size = path.stat().st_size
    with path.open("rb") as handle:
        offset = 0
        while offset + 8 <= file_size:
            handle.seek(offset)
            head = handle.read(8)
            if len(head) < 8:
                break
            size, kind = struct.unpack(">I4s", head)
            header = 8
            if size == 1:
                ext = handle.read(8)
                if len(ext) < 8:
                    break
                size = struct.unpack(">Q", ext)[0]
                header = 16
            elif size == 0:
                size = file_size - offset
            yield kind.decode("latin1", "replace"), offset, size
            if size < header:
                break
            offset += size


def is_faststart(path: Path) -> bool:
    """True when ``moov`` appears before ``mdat`` (or there is no ``mdat``)."""
    try:
        saw_mdat = False
        for kind, _offset, _size in iter_top_level_boxes(path):
            if kind == "moov":
                return not saw_mdat
            if kind == "mdat":
                saw_mdat = True
    except OSError:
        return False
    return False


def probe_media(path: Path) -> dict:
    """Return duration/width/height for a media file using ffprobe."""
    result = {"duration": 0.0, "width": 0, "height": 0}
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration:stream=width,height", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=60, check=True,
        )
        data = json.loads(proc.stdout or "{}")
        stream = (data.get("streams") or [{}])[0]
        result["duration"] = float(data.get("format", {}).get("duration") or 0)
        result["width"] = int(stream.get("width") or 0)
        result["height"] = int(stream.get("height") or 0)
    except Exception:
        pass
    return result


def faststart_command(source: Path, destination: Path) -> list[str]:
    return ["ffmpeg", "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
         "-i", str(source), "-map", "0:v:0", "-map", "0:a?", "-c", "copy",
         "-movflags", "+faststart", "-avoid_negative_ts", "make_zero",
         str(destination)]


def remux_faststart(source: Path, destination: Path, timeout: int = 7200) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)
    subprocess.run(
        faststart_command(source, destination),
        check=True, timeout=timeout,
    )
    if not destination.is_file() or destination.stat().st_size <= 0:
        raise RuntimeError("faststart remux produced an empty file")
    info = probe_media(destination)
    if not info["duration"]:
        raise RuntimeError("faststart remux output is not playable")


def smooth_command(source: Path, destination: Path) -> list[str]:
    return [
        "ffmpeg", "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(source),
        "-vf", f"scale=-2:'min({SMOOTH_HEIGHT},trunc(ih/2)*2)'",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "27",
        "-maxrate", SMOOTH_MAXRATE, "-bufsize", "1800k", "-g", "48",
        "-threads", "2", "-pix_fmt", "yuv420p",
        "-profile:v", "high", "-level", "4.0",
        "-c:a", "aac", "-b:a", SMOOTH_AUDIO_BITRATE, "-ac", "2",
        "-movflags", "+faststart", "-progress", "pipe:1", "-nostats",
        str(destination),
    ]


def safe_variant_path(source: Path, suffix: str) -> Path:
    return source.with_name(source.stem + suffix)


def remove_media_variants(path: Path) -> None:
    for suffix in (".smooth.mp4", ".smooth.tmp.mp4", ".faststart.tmp.mp4"):
        safe_variant_path(path, suffix).unlink(missing_ok=True)
