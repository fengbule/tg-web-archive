import asyncio, base64, bcrypt, hashlib, logging, os, secrets, shutil
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote
from cryptography.fernet import Fernet
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from pydantic import BaseModel, Field
from .db import Database, now
from .telegram_service import TelegramManager
from .downloader import Downloader
from .outbox import OutboxSender

logging.basicConfig(level=os.getenv('LOG_LEVEL','INFO'),format='%(asctime)s %(levelname)s %(name)s %(message)s')
log=logging.getLogger('tvm')
ROOT=Path(os.getenv('DATA_ROOT','/data/telegram-video-manager')).resolve()
MEDIA_ROOT=(ROOT/'media').resolve()
for d in ('media','temp','database','session','config','thumbnails'): (ROOT/d).mkdir(parents=True,exist_ok=True)
db=Database(ROOT/'database'/'app.db'); db.init()
secret=os.environ['SESSION_SECRET']; serializer=URLSafeTimedSerializer(secret,salt='admin-session')
cipher=Fernet(os.environ['CONFIG_ENCRYPTION_KEY'].encode())
tg=TelegramManager(ROOT/'session',ROOT/'thumbnails'/'telegram',db,cipher)
downloader=Downloader(db,tg,ROOT,int(os.getenv('DOWNLOAD_CONCURRENCY','2')),float(os.getenv('MIN_FREE_GB','10')))
outbox=OutboxSender(db,tg,ROOT)

@asynccontextmanager
async def lifespan(app):
    db.recover_interrupted()
    await downloader.start(); await outbox.start(); yield; await outbox.stop(); await downloader.stop()
    await tg.disconnect_all()
app=FastAPI(title='Telegram 视频管理器',lifespan=lifespan,docs_url=None,redoc_url=None)

def config_value(key:str):
    row=db.one('SELECT value FROM config WHERE key=?',(key,)); return row['value'] if row else None
def auth_version(): return config_value('admin_auth_version') or 'legacy'
def verify_pbkdf2(value:str,password:str):
    try:
        salt64,hash64=value.split(':',1); salt=base64.urlsafe_b64decode(salt64); expected=base64.urlsafe_b64decode(hash64)
        actual=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,600_000); return secrets.compare_digest(actual,expected)
    except Exception: return False
def make_pbkdf2(password:str):
    salt=secrets.token_bytes(16); digest=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,600_000)
    return base64.urlsafe_b64encode(salt).decode()+':'+base64.urlsafe_b64encode(digest).decode()

def auth(request:Request):
    token=request.cookies.get('tvm_session')
    if not token: return False
    try:
        payload=serializer.loads(token,max_age=86400*7)
        return payload.get('admin') is True and secrets.compare_digest(str(payload.get('v','legacy')),auth_version())
    except (BadSignature,SignatureExpired): return False

@app.middleware('http')
async def security(request:Request,call_next):
    if request.url.path.startswith('/api/') and request.url.path not in ('/api/auth/login','/api/auth/status') and not auth(request):
        return JSONResponse({'detail':'请先登录管理后台'},status_code=401)
    try: response=await call_next(request)
    except HTTPException as e: return JSONResponse({'detail':str(e.detail)},status_code=e.status_code)
    except Exception:
        log.exception('请求处理失败 path=%s',request.url.path); return JSONResponse({'detail':'操作失败，请稍后重试'},status_code=500)
    if request.url.path.startswith('/api/media/') and request.url.path.endswith('/stream'):
        response.headers['Cache-Control']='private, max-age=3600'
    else: response.headers['Cache-Control']='no-store' if request.url.path.startswith('/api/') else 'no-cache'
    return response

class AdminLogin(BaseModel): password:str
@app.get('/health')
def health(): return {'ok':True}
@app.get('/api/auth/status')
def auth_status(request:Request): return {'authenticated':auth(request)}
def check_admin_password(password:str):
    stored=config_value('admin_password_pbkdf2')
    if stored: return verify_pbkdf2(stored,password)
    pbkdf=os.environ.get('ADMIN_PASSWORD_PBKDF2',''); ok=False
    if pbkdf:
        ok=verify_pbkdf2(pbkdf,password)
    else:
        try: expected=base64.b64decode(os.environ.get('ADMIN_PASSWORD_HASH_B64',''),validate=True)
        except Exception: expected=b''
        try: ok=expected.startswith(b'$2') and bcrypt.checkpw(password.encode(),expected)
        except ValueError: ok=False
    if not pbkdf and not os.environ.get('ADMIN_PASSWORD_HASH_B64'): raise HTTPException(503,'服务器管理员密码配置不安全')
    return ok
@app.post('/api/auth/login')
def admin_login(body:AdminLogin):
    if not check_admin_password(body.password): raise HTTPException(401,'管理员密码错误')
    r=JSONResponse({'ok':True}); r.set_cookie('tvm_session',serializer.dumps({'admin':True,'v':auth_version()}),httponly=True,samesite='strict',secure=os.getenv('COOKIE_SECURE','false').lower()=='true',max_age=86400*7); return r
@app.post('/api/auth/logout')
def admin_logout():
    r=JSONResponse({'ok':True}); r.delete_cookie('tvm_session'); return r

def size_dir(p):
    return sum(x.stat().st_size for x in p.rglob('*') if x.is_file())
@app.get('/api/dashboard')
async def dashboard():
    du=shutil.disk_usage(ROOT); active=db.one("SELECT count(*) n FROM downloads WHERE status IN ('queued','downloading')")['n']; count=db.one('SELECT count(*) n FROM media')['n']
    return {'disk':{'total':du.total,'used':du.used,'free':du.free},'media_bytes':size_dir(ROOT/'media'),'temp_bytes':size_dir(ROOT/'temp'),'video_count':count,'active_downloads':active,'reserve_bytes':downloader.reserve}

@app.get('/api/telegram/status')
async def tg_status(): return await tg.status()
class CredentialReveal(BaseModel): password:str=Field(min_length=1,max_length=200)
def check_view_password(password:str):
    stored=config_value('credential_view_password_pbkdf2')
    return verify_pbkdf2(stored,password) if stored else check_admin_password(password)
@app.post('/api/settings/telegram-credentials/reveal')
def reveal_telegram_credentials(body:CredentialReveal):
    if not check_view_password(body.password): raise HTTPException(403,'查看密码错误，无法查看 API 凭据')
    service=tg.service()
    if not service.api_configured(): raise HTTPException(404,'当前 Telegram 账号尚未配置 API ID 和 API Hash')
    try: api_id,api_hash=service.credentials()
    except Exception: raise HTTPException(500,'已保存的 Telegram API 凭据无法解密')
    row=db.one('SELECT label FROM accounts WHERE id=?',(tg.active_id,))
    return {'account_id':tg.active_id,'label':row['label'] if row else '当前账号','api_id':api_id,'api_hash':api_hash}
@app.get('/api/settings/security')
def security_settings():
    return {'custom_admin_password':bool(config_value('admin_password_pbkdf2')),'has_view_password':bool(config_value('credential_view_password_pbkdf2'))}
class AdminPasswordChange(BaseModel):
    current_password:str=Field(min_length=1,max_length=200)
    new_password:str=Field(min_length=8,max_length=128)
@app.post('/api/settings/passwords/admin')
def change_admin_password(body:AdminPasswordChange):
    if not check_admin_password(body.current_password): raise HTTPException(403,'当前管理员密码错误')
    if secrets.compare_digest(body.current_password,body.new_password): raise HTTPException(400,'新密码不能与当前密码相同')
    db.execute('INSERT OR REPLACE INTO config(key,value) VALUES(?,?)',('admin_password_pbkdf2',make_pbkdf2(body.new_password)))
    db.execute('INSERT OR REPLACE INTO config(key,value) VALUES(?,?)',('admin_auth_version',secrets.token_urlsafe(24)))
    response=JSONResponse({'ok':True,'relogin_required':True})
    response.delete_cookie('tvm_session'); return response
class ViewPasswordChange(BaseModel):
    admin_password:str=Field(min_length=1,max_length=200)
    new_password:str=Field(min_length=8,max_length=128)
@app.post('/api/settings/passwords/view')
def change_view_password(body:ViewPasswordChange):
    if not check_admin_password(body.admin_password): raise HTTPException(403,'管理员密码错误')
    db.execute('INSERT OR REPLACE INTO config(key,value) VALUES(?,?)',('credential_view_password_pbkdf2',make_pbkdf2(body.new_password)))
    return {'ok':True}
class AdminPasswordConfirm(BaseModel): admin_password:str=Field(min_length=1,max_length=200)
@app.delete('/api/settings/passwords/view')
def reset_view_password(body:AdminPasswordConfirm):
    if not check_admin_password(body.admin_password): raise HTTPException(403,'管理员密码错误')
    db.execute("DELETE FROM config WHERE key='credential_view_password_pbkdf2'"); return {'ok':True}
@app.get('/api/accounts')
def accounts(): return tg.list_accounts()
class AccountCreate(BaseModel): label:str=Field(min_length=1,max_length=40)
@app.post('/api/accounts')
def account_create(b:AccountCreate):
    aid=tg.create_account(b.label); tg.activate(aid); return {'id':aid,'active':True}
@app.post('/api/accounts/{account_id}/activate')
def account_activate(account_id:int):
    try: tg.activate(account_id)
    except ValueError as e: raise HTTPException(404,str(e))
    return {'ok':True}
@app.delete('/api/accounts/{account_id}')
async def account_delete(account_id:int):
    try: await tg.remove(account_id)
    except ValueError as e: raise HTTPException(400,str(e))
    return {'ok':True}
class SendCode(BaseModel): phone:str; api_id:int|None=None; api_hash:str|None=None
@app.post('/api/telegram/send-code')
async def send_code(b:SendCode):
    await tg.send_code(b.phone,b.api_id,b.api_hash); return {'ok':True}
class Code(BaseModel): code:str
@app.post('/api/telegram/verify-code')
async def verify_code(b:Code): return {'result':await tg.verify_code(b.code)}
class Password(BaseModel): password:str
@app.post('/api/telegram/verify-password')
async def verify_password(b:Password): await tg.verify_password(b.password); return {'ok':True}
@app.post('/api/telegram/logout')
async def telegram_logout(clear:bool=False): await tg.logout(clear); return {'ok':True}
@app.get('/api/channels')
async def channels(q:str='',refresh:bool=False): return await tg.channels(q,refresh)
@app.get('/api/channels/{channel_id}/videos')
async def videos(channel_id:int,offset_id:int=0,limit:int=30): return await tg.videos(channel_id,offset_id,limit)
@app.get('/api/channels/{channel_id}/videos/{message_id}/thumbnail')
async def telegram_thumbnail(channel_id:int,message_id:int):
    p=await tg.thumbnail(channel_id,message_id)
    if not p: raise HTTPException(404,'该视频没有可用封面')
    return FileResponse(p,media_type='image/jpeg',headers={'Cache-Control':'private, max-age=86400'})

@app.get('/api/dialogs')
async def dialogs(q:str='',limit:int=100):
    try: return await tg.dialogs(q,limit)
    except ValueError as e: raise HTTPException(400,str(e))
@app.get('/api/telegram/saved-messages')
async def saved_messages(): return await tg.saved_messages()
@app.get('/api/dialogs/{peer_id}/messages')
async def dialog_messages(peer_id:int,offset_id:int=0,after_id:int=0,limit:int=40):
    try: return await tg.messages(peer_id,offset_id,after_id,limit)
    except ValueError as e: raise HTTPException(400,str(e))
class SendMessage(BaseModel):
    text:str=Field(min_length=1,max_length=4096)
    reply_to:int|None=None
@app.post('/api/dialogs/{peer_id}/messages')
async def send_message(peer_id:int,b:SendMessage):
    try: return await tg.send_text(peer_id,b.text,b.reply_to)
    except ValueError as e: raise HTTPException(400,str(e))
@app.delete('/api/dialogs/{peer_id}/messages/{message_id}')
async def delete_message(peer_id:int,message_id:int):
    try: await tg.delete_message(peer_id,message_id)
    except ValueError as e: raise HTTPException(400,str(e))
    return {'ok':True}
class ButtonClick(BaseModel): row:int=Field(ge=0,le=20); col:int=Field(ge=0,le=20)
@app.post('/api/dialogs/{peer_id}/messages/{message_id}/click')
async def click_message_button(peer_id:int,message_id:int,b:ButtonClick):
    try: return await tg.click_button(peer_id,message_id,b.row,b.col)
    except ValueError as e: raise HTTPException(400,str(e))
@app.delete('/api/dialogs/{peer_id}')
async def leave_dialog(peer_id:int):
    try: await tg.leave_dialog(peer_id)
    except ValueError as e: raise HTTPException(400,str(e))
    return {'ok':True}
@app.get('/api/telegram/resolve')
async def resolve_target(q:str=Query(min_length=1,max_length=200)):
    try: return await tg.resolve_target(q)
    except ValueError as e: raise HTTPException(404,str(e))
class JoinTarget(BaseModel): target:str=Field(min_length=1,max_length=300)
@app.post('/api/telegram/join')
async def join_target(b:JoinTarget):
    try: return await tg.join_target(b.target)
    except ValueError as e: raise HTTPException(400,str(e))
    except Exception: raise HTTPException(400,'加入失败，请检查链接、账号权限或是否需要管理员审批')

class QueueItem(BaseModel):
    channel_id:int; message_id:int; channel_title:str=''; file_name:str; size:int=0
@app.post('/api/downloads')
def queue(items:list[QueueItem]):
    if not items or len(items)>100: raise HTTPException(400,'请选择 1 到 100 个视频')
    result=[]
    for x in items:
        item=x.model_dump(); item['account_id']=tg.active_id
        i,duplicate=downloader.enqueue(item); result.append({'id':i,'duplicate':duplicate})
    return result
@app.get('/api/downloads')
def downloads(): return db.all('SELECT * FROM downloads ORDER BY id DESC LIMIT 500')
@app.post('/api/downloads/{id}/cancel')
def cancel(id:int): downloader.cancel(id); return {'ok':True}
@app.post('/api/downloads/{id}/pause')
def pause_download(id:int):
    if not downloader.pause(id): raise HTTPException(409,'当前任务不能暂停')
    return {'ok':True}
@app.post('/api/downloads/{id}/resume')
def resume_download(id:int):
    row=db.one('SELECT temp_path FROM downloads WHERE id=?',(id,)); resumed=bool(row and row.get('temp_path') and Path(row['temp_path']).is_file())
    if not downloader.resume(id): raise HTTPException(409,'当前任务不能继续')
    return {'ok':True,'resumed':resumed}
@app.post('/api/downloads/{id}/retry')
def retry(id:int):
    row=db.one('SELECT temp_path FROM downloads WHERE id=?',(id,)); resumed=bool(row and row.get('temp_path') and Path(row['temp_path']).is_file())
    downloader.cancelled.discard(id)
    db.execute("UPDATE downloads SET status='queued',error='',retry_count=0,updated_at=? WHERE id=? AND status IN ('failed','cancelled','paused','retrying')",(now(),id)); return {'ok':True,'resumed':resumed}

@app.get('/api/media')
def media(q:str='',channel_id:int|None=None,sort:str='time'):
    where=[]; args=[]
    if q: where.append('(file_name LIKE ? OR channel_title LIKE ?)'); args += [f'%{q}%',f'%{q}%']
    if channel_id is not None: where.append('channel_id=?'); args.append(channel_id)
    order={'time':'downloaded_at DESC','name':'file_name COLLATE NOCASE','size':'size DESC'}.get(sort,'downloaded_at DESC')
    return db.all('SELECT * FROM media'+((' WHERE '+' AND '.join(where)) if where else '')+' ORDER BY '+order+' LIMIT 1000',args)
class OutboxCreate(BaseModel):
    peer_id:int
    media_id:int
    caption:str=Field(default='',max_length=1024)
@app.post('/api/outbox')
def create_outbox(b:OutboxCreate):
    try: job_id=outbox.enqueue(tg.active_id,b.peer_id,b.media_id,b.caption)
    except ValueError as e: raise HTTPException(400,str(e))
    return {'id':job_id,'status':'queued'}
@app.get('/api/outbox')
def list_outbox(peer_id:int|None=None):
    if peer_id is None: return db.all('SELECT * FROM outbox WHERE account_id=? ORDER BY id DESC LIMIT 100',(tg.active_id,))
    return db.all('SELECT * FROM outbox WHERE account_id=? AND peer_id=? ORDER BY id DESC LIMIT 100',(tg.active_id,peer_id))
@app.post('/api/outbox/{id}/cancel')
def cancel_outbox(id:int):
    if not outbox.cancel(id): raise HTTPException(404,'发送任务不存在')
    return {'ok':True}
@app.post('/api/outbox/{id}/retry')
def retry_outbox(id:int):
    changed=db.execute("UPDATE outbox SET status='queued',uploaded_bytes=0,error='',updated_at=? WHERE id=? AND status IN ('failed','cancelled')",(now(),id)).rowcount
    if not changed: raise HTTPException(409,'当前发送任务不能重试')
    outbox.cancelled.discard(id); return {'ok':True}
@app.get('/api/media/source/{channel_id}/{message_id}')
def media_by_source(channel_id:int,message_id:int):
    x=db.one('SELECT * FROM media WHERE account_id=? AND channel_id=? AND message_id=?',(tg.active_id,channel_id,message_id))
    if not x: raise HTTPException(404,'本地视频不存在')
    return x
def media_row(id):
    x=db.one('SELECT * FROM media WHERE id=?',(id,))
    if not x: raise HTTPException(404,'视频不存在')
    p=Path(x['file_path']).resolve()
    if ROOT not in p.parents or not p.is_file(): raise HTTPException(404,'视频文件不存在')
    return x,p
def safe_unlink(value):
    if not value: return 0
    try:
        p=Path(value).resolve()
        if ROOT not in p.parents or not p.is_file(): return 0
        size=p.stat().st_size; p.unlink(missing_ok=True); return size
    except OSError: return 0
def delete_media_record(x):
    removed=safe_unlink(x.get('file_path')); safe_unlink(x.get('thumb_path'))
    if x.get('download_id'): safe_unlink(str(ROOT/'temp'/f"{x['download_id']}.part"))
    db.execute('DELETE FROM media WHERE id=?',(x['id'],))
    if x.get('download_id'): db.execute('DELETE FROM downloads WHERE id=?',(x['download_id'],))
    return removed
class BulkDelete(BaseModel):
    ids:list[int]=Field(default_factory=list,max_length=1000)
    all:bool=False
    confirmation:str
@app.post('/api/media/bulk-delete')
def bulk_delete_media(b:BulkDelete):
    expected='清空全部视频' if b.all else '删除选中视频'
    if b.confirmation!=expected: raise HTTPException(400,'删除确认文字不正确')
    if not b.all and not b.ids: raise HTTPException(400,'请选择要删除的视频')
    ids=list(dict.fromkeys(b.ids))
    rows=db.all('SELECT * FROM media') if b.all else db.all('SELECT * FROM media WHERE id IN ('+','.join('?' for _ in ids)+')',tuple(ids))
    removed=sum(delete_media_record(x) for x in rows)
    return {'deleted':len(rows),'bytes':removed}
@app.get('/api/media/{id}')
def media_detail(id:int): return media_row(id)[0]
@app.get('/api/media/{id}/sendability')
async def media_sendability(id:int):
    x,_=media_row(id); return await tg.media_sendability(int(x.get('account_id') or 1),x)
@app.get('/api/media/{id}/thumbnail')
def thumbnail(id:int):
    x,_=media_row(id); p=Path(x['thumb_path']).resolve() if x['thumb_path'] else None
    if not p or ROOT not in p.parents or not p.is_file(): raise HTTPException(404,'无缩略图')
    return FileResponse(p,media_type='image/jpeg')
@app.get('/api/media/{id}/stream')
def stream(id:int,request:Request,download:bool=False):
    x,p=media_row(id); size=p.stat().st_size; mime=x['mime']; rng=request.headers.get('range')
    headers={'Accept-Ranges':'bytes','Cache-Control':'private, max-age=3600','Content-Disposition':('attachment' if download else 'inline')+f"; filename*=UTF-8''{quote(x['file_name'])}"}
    if os.getenv('USE_X_ACCEL','false').lower()=='true' and MEDIA_ROOT in p.parents:
        relative=quote(p.relative_to(MEDIA_ROOT).as_posix(),safe='/')
        headers['X-Accel-Redirect']='/protected-media/'+relative
        return Response(media_type=mime,headers=headers)
    if not rng: return FileResponse(p,media_type=mime,headers=headers)
    try:
        unit,val=rng.split('=',1); start_s,end_s=val.split('-',1); start=int(start_s) if start_s else max(0,size-int(end_s)); end=int(end_s) if end_s else size-1
        if unit!='bytes' or start<0 or end>=size or start>end: raise ValueError()
    except ValueError: return Response(status_code=416,headers={'Content-Range':f'bytes */{size}'})
    def iterator():
        with p.open('rb') as f:
            f.seek(start); remain=end-start+1
            while remain:
                chunk=f.read(min(1024*1024,remain));
                if not chunk: break
                remain-=len(chunk); yield chunk
    headers.update({'Content-Range':f'bytes {start}-{end}/{size}','Content-Length':str(end-start+1)})
    return StreamingResponse(iterator(),status_code=206,media_type=mime,headers=headers)
class Rename(BaseModel): name:str=Field(min_length=1,max_length=240)
@app.patch('/api/media/{id}')
def rename(id:int,b:Rename):
    x,p=media_row(id); name=Path(b.name).name
    if name!=b.name or name in ('.','..'): raise HTTPException(400,'文件名不合法')
    new=p.with_name(f"{x['message_id']}_{name}")
    if new.exists() and new!=p: raise HTTPException(409,'同名文件已存在')
    p.rename(new); db.execute('UPDATE media SET file_name=?,file_path=? WHERE id=?',(name,str(new),id)); return {'ok':True}
@app.delete('/api/media/{id}')
def delete_media(id:int):
    x=db.one('SELECT * FROM media WHERE id=?',(id,))
    if not x: raise HTTPException(404,'视频不存在')
    removed=delete_media_record(x); return {'ok':True,'bytes':removed}
@app.post('/api/settings/cleanup-temp')
def cleanup_temp():
    n=0; total=0
    protected={str(Path(x['temp_path']).resolve()) for x in db.all("SELECT temp_path FROM downloads WHERE status IN ('queued','downloading','retrying','pausing','paused') AND temp_path<>''")}
    for p in (ROOT/'temp').glob('*'):
        if p.is_file() and str(p.resolve()) not in protected: total+=p.stat().st_size; p.unlink(); n+=1
    return {'files':n,'bytes':total}

STATIC=Path(__file__).parent/'static'
app.mount('/',StaticFiles(directory=STATIC,html=True),name='static')
