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
    assert c.post('/api/auth/login',json={'password':'wrong'}).status_code==401
    assert c.post('/api/auth/login',json={'password':'test-password-123'}).status_code==200
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
    added=c.post('/api/accounts',json={'label':'备用账号'}); assert added.status_code==200
    aid=added.json()['id']; assert len(c.get('/api/accounts').json())==2
    assert c.post('/api/accounts/1/activate').status_code==200
    assert c.delete(f'/api/accounts/{aid}').status_code==200 and len(c.get('/api/accounts').json())==1
    media=root/'media'/'1'; media.mkdir(parents=True); f=media/'1_test.mp4'; f.write_bytes(b'0123456789')
    cur=db.execute("insert into media(channel_id,message_id,channel_title,file_name,file_path,size,downloaded_at) values(1,1,'测试','test.mp4',?,10,'now')",(str(f),)); mid=cur.lastrowid
    r=c.get(f'/api/media/{mid}/stream',headers={'Range':'bytes=2-5'}); assert r.status_code==206 and r.content==b'2345' and r.headers['content-range']=='bytes 2-5/10'
    assert r.headers['cache-control']=='private, max-age=3600'
    os.environ['USE_X_ACCEL']='true'
    accelerated=c.get(f'/api/media/{mid}/stream')
    assert accelerated.status_code==200 and accelerated.headers['x-accel-redirect'].startswith('/protected-media/')
    assert accelerated.content==b''
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
