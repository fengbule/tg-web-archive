"""Run standalone: isolated DATA_ROOT, no real Telegram or production sessions."""
import base64
import os
import sys
import tempfile
from pathlib import Path

import bcrypt
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['DATA_ROOT']=tempfile.mkdtemp(prefix='enhancement-api-')
os.environ['SESSION_SECRET']='isolated-enhancement-fixture-'*4
os.environ['CONFIG_ENCRYPTION_KEY']='hTt_JVQy8yrH8b8fAoJmM3LhsBVKk24g4pLfqq1JR10='
os.environ['ADMIN_PASSWORD_HASH_B64']=base64.b64encode(bcrypt.hashpw(b'fixture-enhancement',bcrypt.gensalt())).decode()
os.environ['USE_X_ACCEL']='false'
os.environ['COOKIE_SECURE']='false'
from fastapi.testclient import TestClient
from app.main import app,db,transcoder,ROOT
from app.db import now

with TestClient(app) as c:
    c.portal.call(transcoder.stop)
    source=ROOT/'media'/'fixture.mp4';source.write_bytes(b'original-bytes')
    db.execute("INSERT INTO media(channel_id,message_id,channel_title,file_name,file_path,size,downloaded_at,faststart,original_hls_status,preview_status) VALUES(1,1,'test','fixture.mp4',?,?,?,1,'ready','ready')", (str(source),source.stat().st_size,now()))
    for method in ('get','post','delete'):
        assert getattr(c,method)('/api/media/1/enhanced').status_code==401
    assert c.get('/api/media/1/stream?quality=enhanced').status_code==401
    assert c.post('/api/auth/login',json={'password':'fixture-enhancement'}).status_code==200
    assert c.get('/api/media/1/enhanced').json()['status']=='idle'
    assert c.post('/api/media/1/enhanced').json()['status']=='queued'
    assert c.post('/api/media/1/enhanced').json()['status']=='queued'
    assert c.get('/api/media/1/stream?quality=enhanced').status_code==409
    assert c.delete('/api/media/1/enhanced').status_code==200
    assert c.get('/api/media/1/enhanced').json()['status']=='idle'
    assert source.read_bytes()==b'original-bytes'
    output=source.with_name('fixture.enhanced.mp4');output.write_bytes(b'enhanced-video-bytes')
    db.execute("UPDATE media SET enhanced_path=?,enhanced_status='ready',enhanced_progress=100,enhanced_size=? WHERE id=1",(str(output),output.stat().st_size))
    result=c.get('/api/media/1/stream?quality=enhanced&download=true',headers={'Range':'bytes=2-8'})
    assert result.status_code==206 and result.content==b'hanced-'
    from urllib.parse import unquote
    assert '轻度增强.mp4' in unquote(result.headers['content-disposition'])
    assert c.get('/api/media/1/stream?quality=original').content==b'original-bytes'
    assert c.get('/api/media/1/stream?quality=unknown').status_code==400
    assert c.patch('/api/media/1',json={'name':'renamed.mp4'}).status_code==200
    row=db.one('SELECT * FROM media')
    assert Path(row['enhanced_path']).is_file() and not output.exists()
    assert c.get('/api/media/1/stream?quality=enhanced').content==b'enhanced-video-bytes'
    assert c.delete('/api/media/1/enhanced').status_code==200
    assert Path(row['file_path']).read_bytes()==b'original-bytes' and not Path(row['enhanced_path']).exists()
    # Missing derivatives are actionable, and unsafe paths can never be streamed.
    db.execute("UPDATE media SET enhanced_status='ready',enhanced_path='/etc/passwd'")
    assert c.get('/api/media/1/enhanced').json()['status']=='idle'
    assert c.get('/api/media/1/stream?quality=enhanced').status_code==409
    db.execute("UPDATE media SET enhanced_path='' ")
    assert c.delete('/api/media/1').status_code==200
    assert not Path(row['file_path']).exists()
print('ENHANCEMENT_API=PASS (auth, idempotence, cancel, original preservation, Range, attachment, rename, removal, path checks)')
