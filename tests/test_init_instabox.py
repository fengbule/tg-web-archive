"""Ensure deployment initialization never replaces keys or strands existing data."""
from pathlib import Path
import subprocess
import sys

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'init_instabox.py'


def run_init(tmp_path, password='test-only-password-123456'):
    return subprocess.run([sys.executable, str(SCRIPT)], cwd=tmp_path,
                          input=password+'\n', text=True, capture_output=True)


def test_init_preserves_keys_and_does_not_log_password(tmp_path):
    first = run_init(tmp_path)
    assert first.returncode == 0
    env = tmp_path / '.env'
    original = env.read_bytes()
    assert b'test-only-password' not in original
    assert 'test-only-password' not in first.stdout + first.stderr
    assert env.stat().st_mode & 0o777 == 0o600
    assert run_init(tmp_path, 'other-password-123456').returncode == 0
    assert env.read_bytes() == original


def test_init_refuses_data_without_matching_keys(tmp_path):
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data' / 'existing.db').write_bytes(b'existing data')
    assert run_init(tmp_path).returncode != 0
    assert not (tmp_path / '.env').exists()


def test_init_refuses_short_password(tmp_path):
    assert run_init(tmp_path, 'short').returncode != 0
    assert not (tmp_path / '.env').exists()
