"""独立运行的 API 冒烟测试，避免接触真实 Telegram。"""
import os, sys, tempfile, bcrypt
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

root=Path(tempfile.mkdtemp(prefix='tvm-api-'))
os.environ['DATA_ROOT']=str(root)
os.environ['SESSION_SECRET']='test-secret-'*8
os.environ['CONFIG_ENCRYPTION_KEY']='hTt_JVQy8yrH8b8fAoJmM3LhsBVKk24g4pLfqq1JR10='
import base64
os.environ['ADMIN_PASSWORD_HASH_B64']=base64.b64encode(bcrypt.hashpw(b'test-password-123',bcrypt.gensalt())).decode()

from fastapi.testclient import TestClient
from app.main import app,db,tg

with TestClient(app) as c:
    assert c.get('/health').status_code==200
    assert c.get('/api/dashboard').status_code==401
    assert c.get('/api/media/1/playback').status_code==401
    assert c.get('/api/media/1/hls/index.m3u8').status_code==401
    assert c.get('/api/telegram/qr/status').status_code==401
    assert c.post('/api/telegram/qr/start',json={}).status_code==401
    assert c.post('/api/auth/login',json={'password':'wrong'}).status_code==401
    assert c.post('/api/auth/login',json={'password':'test-password-123'}).status_code==200
    assert c.post('/api/telegram/qr/start',json={}).status_code==400
    assert c.post('/api/telegram/qr/start',json={'api_id':1}).status_code==400
    assert c.post('/api/telegram/qr/start',json={'api_id':1,'api_hash':'invalid'}).status_code==422
    qr=c.get('/api/telegram/qr/status')
    assert qr.json()['state']=='idle' and qr.headers['cache-control']=='no-store'
    assert c.post('/api/telegram/qr/cancel').status_code==200
    assert c.get('/api/telegram/qr/status?account_id=999999').status_code==404
    assert c.post('/api/telegram/qr/start?account_id=999999',json={}).status_code==404
    tg.service().save_api(123456,'0123456789abcdef0123456789abcdef')
    denied=c.post('/api/settings/telegram-credentials/reveal',json={'password':'wrong'})
    assert denied.status_code==403 and 'api_hash' not in denied.text.lower()
    revealed=c.post('/api/settings/telegram-credentials/reveal',json={'password':'test-password-123'})
    assert revealed.status_code==200 and revealed.json()['api_id']==123456
    assert revealed.json()['api_hash']=='0123456789abcdef0123456789abcdef'
    assert revealed.headers['cache-control']=='no-store'
    assert c.get('/api/settings/security').json()['has_view_password'] is False
    assert c.post('/api/settings/passwords/view',json={'admin_password':'wrong','new_password':'view-password-456'}).status_code==403
    assert c.post('/api/settings/passwords/view',json={'admin_password':'test-password-123','new_password':'view-password-456'}).status_code==200
    assert c.get('/api/settings/security').json()['has_view_password'] is True
    assert c.post('/api/settings/telegram-credentials/reveal',json={'password':'test-password-123'}).status_code==403
    assert c.post('/api/settings/telegram-credentials/reveal',json={'password':'view-password-456'}).status_code==200
    assert c.request('DELETE','/api/settings/passwords/view',json={'admin_password':'test-password-123'}).status_code==200
    assert c.post('/api/settings/telegram-credentials/reveal',json={'password':'test-password-123'}).status_code==200
    assert c.post('/api/settings/passwords/admin',json={'current_password':'wrong','new_password':'new-admin-password-456'}).status_code==403
    changed=c.post('/api/settings/passwords/admin',json={'current_password':'test-password-123','new_password':'new-admin-password-456'})
    assert changed.status_code==200 and changed.json()['relogin_required']
    assert c.get('/api/dashboard').status_code==401
    assert c.post('/api/auth/login',json={'password':'test-password-123'}).status_code==401
    assert c.post('/api/auth/login',json={'password':'new-admin-password-456'}).status_code==200
    assert c.post('/api/settings/telegram-credentials/reveal',json={'password':'new-admin-password-456'}).status_code==200
    d=c.get('/api/dashboard'); assert d.status_code==200 and 'disk' in d.json()
    accounts=c.get('/api/accounts').json(); assert len(accounts)==1 and accounts[0]['active']
    assert accounts[0]['authorized'] is False
    assert c.post('/api/accounts',json={'label':'  '}).status_code==400
    added=c.post('/api/accounts',json={'label':'备用账号'}); assert added.status_code==200
    aid=added.json()['id']; assert len(c.get('/api/accounts').json())==2
    assert c.patch(f'/api/accounts/{aid}',json={'label':'工作账号'}).status_code==200
    assert c.patch(f'/api/accounts/{aid}',json={'label':'  '}).status_code==400
    assert c.post('/api/accounts/999999/logout').status_code==404
    assert c.post('/api/telegram/verify-password?account_id=999999',json={'password':'test'}).status_code==404
    assert c.post(f'/api/accounts/{aid}/logout').json()['account_id']==aid
    assert c.post('/api/accounts/1/activate').status_code==200
    assert c.delete(f'/api/accounts/{aid}').status_code==200 and len(c.get('/api/accounts').json())==1
    media=root/'media'/'1'; media.mkdir(parents=True); f=media/'1_test.mp4'; f.write_bytes(b'0123456789')
    cur=db.execute("insert into media(channel_id,message_id,channel_title,file_name,file_path,size,downloaded_at) values(1,1,'测试','test.mp4',?,10,'now')",(str(f),)); mid=cur.lastrowid
    playback=c.get(f'/api/media/{mid}/playback').json()
    assert playback['original']['type']=='file'
    assert c.get(f'/api/media/{mid}/hls/index.m3u8').status_code==404
    cache=root/'media'/'.streams'/str(mid);cache.mkdir(parents=True)
    (cache/'index.m3u8').write_text('#EXTM3U\n#EXT-X-ENDLIST\n')
    (cache/'init.mp4').write_bytes(b'init')
    (cache/'segment-00000.m4s').write_bytes(b'segment')
    db.execute("UPDATE media SET faststart=1,original_hls_status='ready' WHERE id=?",(mid,))
    assert c.get(f'/api/media/{mid}/playback').json()['original']['type']=='hls'
    manifest=c.get(f'/api/media/{mid}/hls/index.m3u8')
    assert manifest.status_code==200 and '#EXTM3U' in manifest.text
    assert c.get(f'/api/media/{mid}/hls/init.mp4').content==b'init'
    assert c.get(f'/api/media/{mid}/hls/segment-00000.m4s').content==b'segment'
    for name in ('app.db','segment-00001.m4s','%2e%2e%2fapp.db'):
        assert c.get(f'/api/media/{mid}/hls/{name}').status_code==404
    r=c.get(f'/api/media/{mid}/stream',headers={'Range':'bytes=2-5'}); assert r.status_code==206 and r.content==b'2345' and r.headers['content-range']=='bytes 2-5/10'
    assert r.headers['cache-control']=='private, max-age=3600'
    for value, expected, content_range in [
        ('bytes=-3', b'789', 'bytes 7-9/10'),
        ('bytes=-20', b'0123456789', 'bytes 0-9/10'),
        ('bytes=7-99', b'789', 'bytes 7-9/10'),
        ('bytes=7-', b'789', 'bytes 7-9/10'),
    ]:
        ranged=c.get(f'/api/media/{mid}/stream',headers={'Range':value})
        assert ranged.status_code==206, value
        assert ranged.content==expected and ranged.headers['content-range']==content_range, value
    for value in ('bytes=-0', 'bytes=-', 'bytes=10-', 'bytes=5-2', 'bytes=0-1,4-5', 'bytes=+1-2'):
        invalid=c.get(f'/api/media/{mid}/stream',headers={'Range':value})
        assert invalid.status_code==416 and invalid.headers['content-range']=='bytes */10', value
        assert invalid.headers['cache-control']=='no-store'
    f.write_bytes(b'')
    empty=c.get(f'/api/media/{mid}/stream',headers={'Range':'bytes=0-'})
    assert empty.status_code==416 and empty.headers['content-range']=='bytes */0'
    f.write_bytes(b'0123456789')
    partial=root/'temp'/'999.part'; partial.write_bytes(b'partial')
    db.execute("insert into downloads(id,channel_id,message_id,file_name,status,temp_path,downloaded_bytes,created_at,updated_at) values(999,1,999,'partial.mp4','paused',?,7,'now','now')",(str(partial),))
    assert c.post('/api/downloads/999/cancel').status_code==200
    cancelled=db.one('select * from downloads where id=999')
    assert cancelled['status']=='cancelled' and cancelled['downloaded_bytes']==0 and not partial.exists()
    assert c.post('/api/downloads/999/cancel').status_code==409
    assert c.post('/api/downloads/1000/cancel').status_code==409
    assert c.post('/api/downloads/1000/retry').status_code==409
    db.execute("insert into downloads(id,channel_id,message_id,file_name,status,created_at,updated_at) values(1001,1,1001,'active.mp4','downloading','now','now')")
    assert c.post('/api/downloads/1001/pause').status_code==200
    assert c.post('/api/downloads/1001/resume').status_code==409
    assert c.post('/api/downloads/1001/retry').status_code==409
    from app.main import downloader
    assert 1001 in downloader.pause_requested
    os.environ['USE_X_ACCEL']='true'
    accelerated=c.get(f'/api/media/{mid}/stream')
    assert accelerated.status_code==200 and accelerated.headers['x-accel-redirect'].startswith('/protected-media/')
    assert accelerated.content==b''
    for value in ('bytes=+1-2','bytes=10-','bytes=-0','bytes=0-1,4-5'):
        invalid=c.get(f'/api/media/{mid}/stream',headers={'Range':value})
        assert invalid.status_code==416 and invalid.headers['cache-control']=='no-store'
        assert 'x-accel-redirect' not in invalid.headers
    valid_accelerated=c.get(f'/api/media/{mid}/stream',headers={'Range':'bytes=-3'})
    assert valid_accelerated.status_code==200 and 'x-accel-redirect' in valid_accelerated.headers
    os.environ.pop('USE_X_ACCEL')
    assert c.patch(f'/api/media/{mid}',json={'name':'../bad.mp4'}).status_code==400
    assert c.delete(f'/api/media/{mid}').status_code==200 and not f.exists()
    ids=[]
    for n in (2,3,4):
        fp=media/f'{n}_bulk.mp4'; fp.write_bytes(b'x'*n)
        cur=db.execute("insert into media(channel_id,message_id,channel_title,file_name,file_path,size,downloaded_at) values(1,?,'测试','bulk.mp4',?,?,'now')",(n,str(fp),n)); ids.append((cur.lastrowid,fp))
    bad=c.post('/api/media/bulk-delete',json={'ids':[ids[0][0]],'all':False,'confirmation':'错误'}); assert bad.status_code==400
    bulk=c.post('/api/media/bulk-delete',json={'ids':[ids[0][0],ids[1][0]],'all':False,'confirmation':'删除选中视频'}); assert bulk.status_code==200 and bulk.json()['deleted']==2
    assert not ids[0][1].exists() and not ids[1][1].exists() and ids[2][1].exists()
    clear=c.post('/api/media/bulk-delete',json={'ids':[],'all':True,'confirmation':'清空全部视频'}); assert clear.status_code==200 and clear.json()['deleted']==1 and not ids[2][1].exists()
db.close()
print('API_SMOKE=PASS')
