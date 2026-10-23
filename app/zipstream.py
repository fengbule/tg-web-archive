"""Streaming ZIP writer for "download selected videos" without temp copies."""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Iterable


class _StreamSink:
    """Minimal unseekable file object understood by :mod:`zipfile`."""

    def __init__(self):
        self.buffer = bytearray()
        self.position = 0

    def write(self, data):
        data = bytes(data)
        self.buffer.extend(data)
        self.position += len(data)
        return len(data)

    def tell(self):
        return self.position

    def flush(self):
        return None

    def seek(self, *_args, **_kwargs):
        raise OSError("stream is not seekable")


def _unique_name(name: str, used: set[str]) -> str:
    candidate = name or "video.mp4"
    if candidate not in used:
        used.add(candidate)
        return candidate
    path = Path(candidate)
    for index in range(2, 1000):
        alt = f"{path.stem} ({index}){path.suffix}"
        if alt not in used:
            used.add(alt)
            return alt
    return f"{path.stem}-{len(used)}{path.suffix}"


def zip_media_files(items: Iterable[tuple[str, Path]], chunk_size: int = 1024 * 1024):
    """Yield a ZIP archive as bytes; entries are stored (no compression)."""
    sink = _StreamSink()
    used: set[str] = set()
    archive = zipfile.ZipFile(sink, "w", zipfile.ZIP_STORED, allowZip64=True)
    try:
        for name, path in items:
            info = zipfile.ZipInfo(_unique_name(name, used))
            info.file_size = Path(path).stat().st_size
            info.compress_type = zipfile.ZIP_STORED
            info.flag_bits |= 0x08  # data descriptor, required for streams
            # The local header cannot be rewritten on an HTTP stream. Reserve
            # ZIP64 fields up front so large videos (including >4 GiB) work.
            with archive.open(info, "w", force_zip64=True) as target, Path(path).open("rb") as source:
                while True:
                    chunk = source.read(chunk_size)
                    if not chunk:
                        break
                    target.write(chunk)
                    if len(sink.buffer) >= chunk_size:
                        yield bytes(sink.buffer)
                        sink.buffer.clear()
        archive.close()
        if sink.buffer:
            yield bytes(sink.buffer)
            sink.buffer.clear()
    finally:
        try:
            archive.close()
        except Exception:
            pass
