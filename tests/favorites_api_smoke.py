"""Authenticated route checks in a disposable database, with no Telegram I/O."""
import base64, os, tempfile, subprocess, sys
from pathlib import Path
import bcrypt
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

os.environ['DATA_ROOT'] = tempfile.mkdtemp(prefix='tvm-favorites-api-')
os.environ['SESSION_SECRET'] = 'disposable-favorites-api-' * 4
os.environ['CONFIG_ENCRYPTION_KEY'] = Fernet.generate_key().decode()
os.environ['ADMIN_PASSWORD_HASH_B64'] = base64.b64encode(bcrypt.hashpw(b'fixture-favorites-password', bcrypt.gensalt())).decode()
os.environ.pop('TELEGRAM_CLIENT_CONFIG', None)
from app.main import app, db, ROOT
from app.db import now

with TestClient(app) as client:
    payload = {'account_id': 1, 'channel_id': 42, 'message_id': 7, 'file_name': '<script>alert(1)</script>.mp4'}
    for method, route in [('GET', '/api/favorites'), ('PUT', '/api/favorites'), ('DELETE', '/api/favorites/1/42/7')]:
        assert client.request(method, route, json=payload if method == 'PUT' else None).status_code == 401
    assert client.post('/api/auth/login', json={'password': 'fixture-favorites-password'}).status_code == 200
    for _ in range(2): assert client.put('/api/favorites', json=payload).status_code == 200
    assert client.get('/api/favorites').json()['total'] == 1
    assert client.put('/api/favorites', json={**payload, 'account_id': 999}).status_code == 400
    assert client.put('/api/favorites', json={'media_id': 999}).status_code == 404
    for invalid in ({}, {**payload, 'size': -1}, {**payload, 'file_name': 'x' * 1025}, {**payload, 'message_id': 0}):
        assert client.put('/api/favorites', json=invalid).status_code in (400, 422)
    assert client.get('/api/favorites?limit=101').status_code == 422
    assert client.get('/api/favorites?state=bad').status_code == 422
    assert client.get('/api/favorites?offset=-1').status_code == 422
    path = ROOT / 'media' / 'clip.mp4'; path.write_bytes(b'fixture')
    mid = db.execute("INSERT INTO media(channel_id,message_id,channel_title,file_name,file_path,size,downloaded_at) VALUES(42,7,'频道','本地视频.mp4',?,7,?)", (str(path), now())).lastrowid
    assert client.get('/api/media').json()[0]['is_favorite'] is True
    assert client.get(f'/api/media/{mid}').json()['is_favorite'] is True
    assert client.get('/api/favorites?state=downloaded').json()['items'][0]['media_id'] == mid
    assert client.put('/api/favorites', json={'media_id': mid, 'account_id': 999}).json()['account_id'] == 1
    for _ in range(2): assert client.delete('/api/favorites/1/42/7').status_code == 200
    assert client.get('/api/media').json()[0]['is_favorite'] is False
    assert client.get('/api/favorites').json()['total'] == 0
    assert path.exists() and db.one('SELECT count(*) n FROM outbox')['n'] == 0
    assert db.one('SELECT count(*) n FROM downloads')['n'] == 0
    assert client.put('/api/favorites', json={'media_id': mid}).status_code == 200
db.close()
subprocess.run([sys.executable, '-c', 'from app.main import favorites,db; result=favorites.listing(); assert result["total"]==1 and result["items"][0]["downloaded"]; db.close()'], check=True)
print('FAVORITES_API=PASS (authentication, validation, idempotency, source linkage, no upload/download side effects)')
