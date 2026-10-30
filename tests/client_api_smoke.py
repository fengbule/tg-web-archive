"""Isolated authentication/account routing/error mapping checks; no Telegram network."""
import os,sys,tempfile,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['DATA_ROOT']=tempfile.mkdtemp(prefix='tvm-client-api-')
os.environ['SESSION_SECRET']='test-client-secret-'*5
os.environ['CONFIG_ENCRYPTION_KEY']='hTt_JVQy8yrH8b8fAoJmM3LhsBVKk24g4pLfqq1JR10='
os.environ['ADMIN_PASSWORD_PBKDF2']=''
import base64,bcrypt
os.environ['ADMIN_PASSWORD_HASH_B64']=base64.b64encode(bcrypt.hashpw(b'test-client-password',bcrypt.gensalt())).decode()
from fastapi.testclient import TestClient
from app.main import app,tg,transcoder,db
from telethon.errors import FloodWaitError,ChatWriteForbiddenError
calls=[]
class Service:
    async def client_dialogs(self,*args):return {'items':[],'account_id':2,'next_cursor':None}
    async def client_send(self,*args):calls.append(args);return {'id':3,'text':args[1]}
    async def client_target(self,*args):return {'title':'Test','status':'requested'}
    async def client_action(self,*args):
        if args[1]=='pin':raise FloodWaitError(request=None,capture=17)
        if args[1]=='mute':raise ChatWriteForbiddenError(request=None)
        calls.append(args);return {'ok':True}
original=tg.service
def service(a=None):return Service() if a==2 else original(a)
with TestClient(app) as c:
    c.portal.call(transcoder.stop)
    for method,path in [('GET','/dialogs'),('POST','/target/join'),('POST','/dialogs/1/messages'),('POST','/dialogs/1/actions')]:assert c.request(method,'/api/client'+path+'?account_id=2',json={}).status_code==401
    assert c.post('/api/auth/login',json={'password':'test-client-password'}).status_code==200
    tg.service=service
    assert c.get('/api/client/dialogs').status_code==422
    assert c.get('/api/client/dialogs?account_id=99999').status_code==404
    assert c.get('/api/client/dialogs?account_id=2').json()['account_id']==2
    message={'text':'hello','reply_to':9,'request_id':str(uuid.uuid4())}
    assert c.post('/api/client/dialogs/123/messages?account_id=2',json=message).status_code==200
    assert calls[-1][:3]==(123,'hello',9)
    for text in ('   ','😀'*3000):assert c.post('/api/client/dialogs/123/messages?account_id=2',json={**message,'text':text}).status_code==422
    limited=c.post('/api/client/dialogs/123/actions?account_id=2',json={'action':'pin'});assert limited.status_code==429 and limited.headers['retry-after']=='17'
    assert c.post('/api/client/dialogs/123/actions?account_id=2',json={'action':'mute'}).status_code==403
    assert c.post('/api/client/dialogs/123/actions?account_id=2',json={'action':'destroy'}).status_code==422
    assert c.post('/api/client/target/join?account_id=2',json={'target':'@test'}).json()['status']=='requested'
    assert db.one('SELECT count(*) n FROM media')['n']==0
    tg.service=original
    aid=tg.create_account('Isolated upload account')
    from app.db import now
    mid=db.execute("INSERT INTO media(account_id,channel_id,message_id,channel_title,file_name,file_path,size,downloaded_at) VALUES(1,1,1,'test','test.mp4','/nonexistent-test',1,?)",(now(),)).lastrowid
    queued=c.post('/api/outbox',json={'account_id':aid,'peer_id':123,'media_id':mid});assert queued.status_code==200
    assert db.one('SELECT account_id FROM outbox WHERE id=?',(queued.json()['id'],))['account_id']==aid
    assert not c.get('/api/outbox?account_id=1').json()
    assert len(c.get('/api/outbox?account_id='+str(aid)).json())==1
    assert c.post('/api/outbox',json={'account_id':99999,'peer_id':123,'media_id':mid}).status_code==400
print('CLIENT_API=PASS (auth, explicit account, validation, reply, approval pending, flood/permission errors, no local media changes)')
