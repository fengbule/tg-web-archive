import io
import struct
import zipfile
from pathlib import Path

from app.media_tools import is_faststart, iter_top_level_boxes, smooth_command
from app.zipstream import zip_media_files


def box(kind: bytes, payload: bytes = b"") -> bytes:
    return struct.pack(">I4s", 8 + len(payload), kind) + payload


def test_moov_after_mdat_is_not_faststart(tmp_path):
    path = tmp_path / "slow.mp4"
    path.write_bytes(box(b"ftyp", b"isom") + box(b"mdat", b"x" * 32) + box(b"moov", b"y" * 16))
    kinds = [kind for kind, _offset, _size in iter_top_level_boxes(path)]
    assert kinds == ["ftyp", "mdat", "moov"]
    assert is_faststart(path) is False


def test_moov_before_mdat_is_faststart(tmp_path):
    path = tmp_path / "fast.mp4"
    path.write_bytes(box(b"ftyp", b"isom") + box(b"moov", b"y" * 16) + box(b"mdat", b"x" * 32))
    assert is_faststart(path) is True


def test_missing_or_empty_file_is_safe(tmp_path):
    path = tmp_path / "empty.mp4"
    path.write_bytes(b"")
    assert is_faststart(path) is False
    assert is_faststart(tmp_path / "missing.mp4") is False


def test_smooth_command_uses_480p_and_faststart(tmp_path):
    command = smooth_command(tmp_path / "in.mp4", tmp_path / "out.mp4")
    joined = " ".join(command)
    assert "min(480,trunc(ih/2)*2)" in joined
    assert "+faststart" in joined
    assert "libx264" in joined


def test_zip_stream_roundtrip_unicode(tmp_path):
    first = tmp_path / "a.bin"
    second = tmp_path / "b.bin"
    first.write_bytes(b"hello" * 200)
    second.write_bytes(b"world" * 300)
    payload = b"".join(zip_media_files([("测试 视频.bin", first), ("b.bin", second)], chunk_size=64))
    archive = zipfile.ZipFile(io.BytesIO(payload))
    assert archive.namelist() == ["测试 视频.bin", "b.bin"]
    assert archive.read("测试 视频.bin") == first.read_bytes()
    assert archive.read("b.bin") == second.read_bytes()


def test_zip_stream_deduplicates_names(tmp_path):
    path = tmp_path / "same.bin"
    path.write_bytes(b"data")
    payload = b"".join(zip_media_files([("same.bin", path), ("same.bin", path)]))
    archive = zipfile.ZipFile(io.BytesIO(payload))
    assert archive.namelist() == ["same.bin", "same (2).bin"]


def test_zip_stream_large_entry_uses_zip64(tmp_path, monkeypatch):
    # Exercise the >2 GiB transition without allocating gigabytes in CI.
    monkeypatch.setattr(zipfile, 'ZIP64_LIMIT', 512)
    path = tmp_path / 'large.bin'
    path.write_bytes(b'large-video' * 200)
    payload = b''.join(zip_media_files([('large.bin', path)], chunk_size=64))
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert archive.testzip() is None
        assert archive.read('large.bin') == path.read_bytes()
        assert archive.getinfo('large.bin').extract_version >= 45
