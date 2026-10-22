"""Create independent credentials without logging them; preserve existing keys."""
import base64
import getpass
import hashlib
import os
from pathlib import Path
import secrets
import sys


def main():
    env = Path('.env')
    if env.exists():
        print('Existing .env preserved.')
        return
    if Path('data').exists() and any(Path('data').iterdir()):
        sys.exit('Data exists without .env. Restore matching keys from backup.')
    if sys.stdin.isatty():
        password = getpass.getpass('New administrator password (at least 16 characters): ')
        if password != getpass.getpass('Repeat password: '):
            sys.exit('Passwords differ.')
    else:
        password = sys.stdin.readline().rstrip('\r\n')
    if len(password) < 16:
        sys.exit('Password must have at least 16 characters.')
    salt = secrets.token_bytes(18)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 600_000)
    b64 = lambda b: base64.urlsafe_b64encode(b).decode()
    values = {
        'ADMIN_PASSWORD_PBKDF2': b64(salt) + ':' + b64(digest),
        'SESSION_SECRET': secrets.token_hex(32),
        'CONFIG_ENCRYPTION_KEY': b64(secrets.token_bytes(32)),
        'DATA_ROOT': '/data/telegram-video-manager', 'HTTP_PORT': '8081',
        'MIN_FREE_GB': '5', 'DOWNLOAD_CONCURRENCY': '2', 'COOKIE_SECURE': 'true',
        'USE_X_ACCEL': 'true', 'APP_VERSION': '1.2.1',
        'APP_UID': str(os.getuid()), 'APP_GID': str(os.getgid()),
    }
    fd = os.open(env, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(''.join(k + '=' + v + '\n' for k, v in values.items()))
    print('Independent .env created; no credentials printed.')


if __name__ == '__main__':
    main()
