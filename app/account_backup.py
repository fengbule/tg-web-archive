"""Portable, password-encrypted Telegram authorizations; never export server secrets."""
import base64
import hashlib
import json
import secrets
import sqlite3
import struct
import binascii
import uuid
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from telethon.crypto import AuthKey
from telethon.sessions import MemorySession, SQLiteSession, StringSession

from .db import now

FORMAT = 'nebula-accounts-v1'
MAX_BACKUP_BYTES = 2 * 1024 * 1024


def session_state(manager, row):
    """Read one consistent authorization without creating/connecting another client."""
    service = manager.services.get(row['id'])
    session = getattr(getattr(service, 'client', None), 'session', None)
    if session and session.auth_key:
        return StringSession.save(session)
    path = manager.session_dir / (row['session_name'] + '.session')
    if not path.is_file() or not path.stat().st_size:
        return None
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5) as conn:
        data = conn.execute('SELECT dc_id,server_address,port,auth_key FROM sessions LIMIT 1').fetchone()
    if not data or not data[3]:
        return None
    memory = MemorySession()
    memory.set_dc(data[0], data[1], data[2])
    memory.auth_key = AuthKey(bytes(data[3]))
    return StringSession.save(memory)


def collect_accounts(manager, account_ids=None):
    rows = manager.db.all('SELECT * FROM accounts ORDER BY id')
    if account_ids is not None:
        wanted = set(account_ids)
        rows = [r for r in rows if r['id'] in wanted]
        if {r['id'] for r in rows} != wanted:
            raise ValueError('选择的账号不存在，请刷新后重试')
    if not rows or len(rows) > 100:
        raise ValueError('每次请选择 1 至 100 个账号')
    result = []
    for row in rows:
        service = manager.service(row['id'])
        if service.ending_session:
            raise ValueError('账号正在结束会话，请完成后再备份')
        credentials = service.credentials() if service.api_configured() else None
        result.append({'label': row['label'], 'api_id': credentials[0] if credentials else None,
                       'api_hash': credentials[1] if credentials else None,
                       'test_mode': service._cfg('api_test_mode') == '1',
                       'session': session_state(manager, row)})
    return {'format': FORMAT, 'created_at': now(), 'accounts': result}


def _fernet(password, salt):
    key = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 600_000)
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_backup(payload, password):
    salt = secrets.token_bytes(16)
    token = _fernet(password, salt).encrypt(json.dumps(payload, ensure_ascii=False).encode())
    return json.dumps({'format': FORMAT, 'salt': base64.urlsafe_b64encode(salt).decode(),
                       'data': token.decode()}, separators=(',', ':')).encode()


def decrypt_backup(raw, password):
    try:
        if len(raw) > MAX_BACKUP_BYTES:
            raise ValueError()
        envelope = json.loads(raw)
        if envelope['format'] != FORMAT:
            raise ValueError()
        salt = base64.b64decode(envelope['salt'], altchars=b'-_', validate=True)
        if len(salt) != 16:
            raise ValueError()
        payload = json.loads(_fernet(password, salt).decrypt(envelope['data'].encode()))
        rows = payload['accounts']
        if payload['format'] != FORMAT or not isinstance(rows, list) or not 1 <= len(rows) <= 100:
            raise ValueError()
        for row in rows:
            if not isinstance(row['label'], str) or not 1 <= len(row['label'].strip()) <= 40:
                raise ValueError()
            if row['api_id'] is not None:
                if type(row['api_id']) is not int or row['api_id'] <= 0:
                    raise ValueError()
                if not isinstance(row['api_hash'], str) or len(row['api_hash']) != 32 or any(c not in '0123456789abcdefABCDEF' for c in row['api_hash']):
                    raise ValueError()
            elif row['api_hash'] is not None or row['session']:
                raise ValueError()
            if type(row['test_mode']) is not bool:
                raise ValueError()
            if row['session'] is not None:
                if not isinstance(row['session'], str) or not 1 <= len(row['session']) <= 512:
                    raise ValueError()
                state = StringSession(row['session'])
                if not state.auth_key or len(state.auth_key.key) != 256 or not 1 <= state.dc_id <= 5:
                    raise ValueError()
        return rows
    except (ValueError, KeyError, TypeError, AttributeError, InvalidToken, UnicodeError, struct.error, binascii.Error):
        raise ValueError('备份密码错误，或文件损坏 / 格式不受支持') from None


def restore_accounts(manager, rows):
    """Add new slots atomically, skip duplicate auth keys, never activate/connect them."""
    existing = set()
    for row in manager.db.all('SELECT * FROM accounts'):
        state = session_state(manager, row)
        if state:
            existing.add(hashlib.sha256(StringSession(state).auth_key.key).digest())
    files, imported, skipped = [], [], 0
    with manager.db.lock:
        conn = manager.db.conn()
        try:
            conn.execute('BEGIN IMMEDIATE')
            for row in rows:
                state = StringSession(row['session']) if row['session'] else None
                fingerprint = hashlib.sha256(state.auth_key.key).digest() if state else None
                if fingerprint and fingerprint in existing:
                    skipped += 1
                    continue
                name = 'account_' + uuid.uuid4().hex
                if state:
                    path = manager.session_dir / (name + '.session')
                    files.append(path)
                    session = SQLiteSession(str(path))
                    try:
                        session.set_dc(state.dc_id, state.server_address, state.port)
                        session.auth_key = state.auth_key
                        session.save()
                    finally:
                        session.close()
                    path.chmod(0o600)
                cur = conn.execute('INSERT INTO accounts(label,session_name,created_at) VALUES(?,?,?)',
                                   (row['label'].strip(), name, now()))
                aid = cur.lastrowid
                if state:
                    conn.execute('INSERT INTO config(key,value) VALUES(?,?)',
                                 (f'account:{aid}:restore_pending','1'))
                if row['api_id'] is not None:
                    for key, value in [('api_id', str(row['api_id'])), ('api_hash', row['api_hash'])]:
                        conn.execute('INSERT INTO config(key,value) VALUES(?,?)',
                                     (f'account:{aid}:{key}', manager.cipher.encrypt(value.encode()).decode()))
                    conn.execute('INSERT INTO config(key,value) VALUES(?,?)',
                                 (f'account:{aid}:api_test_mode', '1' if row['test_mode'] else '0'))
                imported.append(aid)
                if fingerprint:
                    existing.add(fingerprint)
            conn.commit()
        except Exception:
            conn.rollback()
            for path in files:
                for suffix in ('', '-journal', '-wal', '-shm'):
                    Path(str(path) + suffix).unlink(missing_ok=True)
            raise
    return {'imported': len(imported), 'skipped': skipped, 'account_ids': imported}
