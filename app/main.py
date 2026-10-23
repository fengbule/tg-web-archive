import asyncio, base64, bcrypt, hashlib, json, logging, os, re, secrets, shutil
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
from .transcoder import Transcoder
from .zipstream import zip_media_files
from .account_backup import collect_accounts, encrypt_backup, decrypt_backup, restore_accounts, MAX_BACKUP_BYTES

logging.basicConfig(level=os.getenv('LOG_LEVEL','INFO'),format='%(asctime)s %(levelname)s %(name)s %(message)s')
log=logging.getLogger('tvm')
ROOT=Path(os.getenv('DATA_ROOT','/data/telegram-video-manager')).resolve()
MEDIA_ROOT=(ROOT/'media').resolve()
for d in ('media','temp','database','session','config','thumbnails'): (ROOT/d).mkdir(parents=True,exist_ok=True)
db=Database(ROOT/'database'/'app.db'); db.init()
secret=os.environ['SESSION_SECRET']; serializer=URLSafeTimedSerializer(secret,salt='admin-session')
cipher=Fernet(os.environ['CONFIG_ENCRYPTION_KEY'].encode())
tg=TelegramManager(ROOT/'session',ROOT/'thumbnails'/'telegram',db,cipher)
if os.getenv('TELEGRAM_CLIENT_CONFIG'):
    client_config=json.loads(Path(os.environ['TELEGRAM_CLIENT_CONFIG']).read_text())
    if not tg.service().api_configured():
        tg.service().save_api(int(client_config['api_id']),client_config['api_hash'],test_mode=client_config.get('test_only') is True)
    elif tg.service()._cfg('api_test_mode') is None:
        saved_id,saved_hash=tg.service().credentials()
        mode=client_config.get('test_only') is True and saved_id==int(client_config['api_id']) and secrets.compare_digest(saved_hash,client_config['api_hash'])
        db.execute('INSERT OR REPLACE INTO config(key,value) VALUES(?,?)',(tg.service()._key('api_test_mode'),'1' if mode else '0'))
        del saved_id,saved_hash
    del client_config
downloader=Downloader(db,tg,ROOT,int(os.getenv('DOWNLOAD_CONCURRENCY','2')),float(os.getenv('MIN_FREE_GB','10')))
transcoder=Transcoder(db,ROOT,os.getenv('AUTO_SMOOTH','false').lower()=='true')
downloader.transcoder=transcoder
outbox=OutboxSender(db,tg,ROOT)

@asynccontextmanager
async def lifespan(app):
    db.recover_interrupted()
    await downloader.start(); await transcoder.start(); await outbox.start(); yield
    await outbox.stop(); await transcoder.stop(); await downloader.stop()
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
    if request.url.path.startswith('/api/media/') and request.url.path.endswith('/stream') and response.status_code in (200,206):
        response.headers['Cache-Control']='private, max-age=3600'
    elif request.url.path.startswith('/api/') and request.url.path.endswith('/thumbnail') and response.status_code==200:
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
async def tg_status(): return {**await tg.status(),'qr_test_mode':tg.service()._cfg('api_test_mode')=='1'}
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
async def accounts(): return await tg.list_accounts()
class AccountBackupRequest(BaseModel):
    admin_password:str=Field(min_length=1,max_length=200)
    backup_password:str=Field(min_length=12,max_length=200)
    account_ids:list[int]|None=Field(default=None,min_length=1,max_length=100)
class AccountRestoreRequest(BaseModel):
    admin_password:str=Field(min_length=1,max_length=200)
    backup_password:str=Field(min_length=12,max_length=200)
    backup:str=Field(min_length=1,max_length=MAX_BACKUP_BYTES)
@app.post('/api/accounts/backup/export')
async def export_accounts(body:AccountBackupRequest):
    if not await asyncio.to_thread(check_admin_password,body.admin_password): raise HTTPException(403,'管理员密码错误')
    try:
        payload=collect_accounts(tg,body.account_ids)
        content=await asyncio.to_thread(encrypt_backup,payload,body.backup_password)
    except ValueError as e: raise HTTPException(400,str(e)) from None
    except Exception: raise HTTPException(409,'账号授权暂不可读取，请稍后重试') from None
    return Response(content,media_type='application/octet-stream',headers={
        'Content-Disposition':'attachment; filename="nebula-accounts-'+now()[:10]+'.nebula"',
        'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
@app.post('/api/accounts/backup/import')
async def import_accounts(body:AccountRestoreRequest):
    if not await asyncio.to_thread(check_admin_password,body.admin_password): raise HTTPException(403,'管理员密码错误')
    try:
        rows=await asyncio.to_thread(decrypt_backup,body.backup,body.backup_password)
        return restore_accounts(tg,rows)
    except ValueError as e: raise HTTPException(400,str(e)) from None
    except Exception: raise HTTPException(409,'恢复未完成，已有账号保持不变，请检查备份后重试') from None
class AccountCreate(BaseModel): label:str=Field(min_length=1,max_length=40)
@app.post('/api/accounts')
def account_create(b:AccountCreate):
    if not b.label.strip(): raise HTTPException(400,'账号名称不能为空')
    aid=tg.create_account(b.label); tg.activate(aid); return {'id':aid,'active':True}
@app.patch('/api/accounts/{account_id}')
def account_rename(account_id:int,b:AccountCreate):
    try: tg.rename_account(account_id,b.label)
    except ValueError as e: raise HTTPException(400,str(e))
    return {'ok':True}
@app.post('/api/accounts/{account_id}/activate')
def account_activate(account_id:int):
    try: tg.activate(account_id)
    except ValueError as e: raise HTTPException(404,str(e))
    return {'ok':True}
@app.delete('/api/accounts/{account_id}')
async def account_delete(account_id:int):
    try: await tg.remove(account_id)
    except ValueError as e: raise HTTPException(400,str(e))
    except Exception: raise HTTPException(502,'无法确认 Telegram 会话已结束，已保留账号和 Session，请稍后重试') from None
    return {'ok':True}
@app.post('/api/accounts/{account_id}/logout')
async def account_logout(account_id:int):
    try: tg.service(account_id)
    except ValueError as e: raise HTTPException(404,str(e))
    try: await tg.logout(clear=True,account_id=account_id)
    except ValueError as e: raise HTTPException(409,str(e))
    except Exception: raise HTTPException(502,'无法确认 Telegram 会话已结束，已保留 Session，请稍后重试') from None
    return {'ok':True,'account_id':account_id}
class SendCode(BaseModel): phone:str; api_id:int|None=None; api_hash:str|None=None
class QRStart(BaseModel):
    api_id:int|None=Field(default=None,gt=0)
    api_hash:str|None=Field(default=None,pattern=r'^[a-fA-F0-9]{32}$')
def qr_service(account_id):
    try: return tg.service(account_id)
    except ValueError: raise HTTPException(404,'Telegram 账号不存在') from None
@app.post('/api/telegram/qr/start')
async def qr_start(b:QRStart,account_id:int|None=None):
    service=qr_service(account_id)
    try:
        if bool(b.api_id)!=bool(b.api_hash): raise HTTPException(400,'请同时填写 API ID 和 API Hash')
        if b.api_id:
            # Do not replace a live account's API configuration or session.
            if service.api_configured() and (await service.status())['authorized']:
                return {'state':'authorized','account_id':service.account_id}
            await service.disconnect()
            service.save_api(b.api_id,b.api_hash)
        if not service.api_configured(): raise HTTPException(400,'扫码前仍需填写一次 Telegram API ID 和 API Hash')
        state=await service.qr_login.start(await service.get_client())
        return {**state,'account_id':service.account_id}
    except HTTPException: raise
    except Exception: raise HTTPException(502,'无法连接 Telegram 生成二维码，请检查 API 凭据和服务器网络') from None
@app.get('/api/telegram/qr/status')
def qr_status(account_id:int|None=None):
    service=qr_service(account_id)
    return {**service.qr_login.snapshot(),'account_id':service.account_id}
@app.post('/api/telegram/qr/cancel')
async def qr_cancel(account_id:int|None=None):
    await qr_service(account_id).qr_login.cancel()
    return {'ok':True}
@app.post('/api/telegram/send-code')
async def send_code(b:SendCode,account_id:int|None=None):
    await qr_service(account_id).send_code(b.phone,b.api_id,b.api_hash); return {'ok':True}
class Code(BaseModel): code:str
@app.post('/api/telegram/verify-code')
async def verify_code(b:Code,account_id:int|None=None): return {'result':await qr_service(account_id).verify_code(b.code)}
class Password(BaseModel): password:str
@app.post('/api/telegram/verify-password')
async def verify_password(b:Password,account_id:int|None=None): await qr_service(account_id).verify_password(b.password); return {'ok':True}
@app.post('/api/telegram/logout')
async def telegram_logout(clear:bool=False,account_id:int|None=None): return await account_logout(account_id if account_id is not None else tg.active_id)
@app.get('/api/channels')
async def channels(q:str='',refresh:bool=False): return await tg.channels(q,refresh)
@app.get('/api/channels/{channel_id}/videos')
async def videos(channel_id:int,offset_id:int=0,limit:int=30): return await tg.videos(channel_id,offset_id,limit)
@app.get('/api/channels/{channel_id}/videos/{message_id}/thumbnail')
async def telegram_thumbnail(channel_id:int,message_id:int,account_id:int|None=None):
    service=qr_service(account_id if account_id is not None else tg.active_id)
    try: p=await service.thumbnail(channel_id,message_id)
    except TimeoutError: raise HTTPException(504,'封面读取超时，请点击重试') from None
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
    channel_id:int; message_id:int; channel_title:str=''; file_name:str; size:int=0; account_id:int|None=None
@app.post('/api/downloads')
def queue(items:list[QueueItem]):
    if not items or len(items)>100: raise HTTPException(400,'请选择 1 到 100 个视频')
    for x in items:
        if x.account_id is not None and not db.one('SELECT id FROM accounts WHERE id=?',(x.account_id,)): raise HTTPException(400,'Telegram 账号不存在')
    result=[]
    for x in items:
        item=x.model_dump(); item['account_id']=x.account_id if x.account_id is not None else tg.active_id
        i,duplicate=downloader.enqueue(item); result.append({'id':i,'duplicate':duplicate})
    return result
@app.get('/api/downloads')
def downloads(): return db.all('SELECT * FROM downloads ORDER BY id DESC LIMIT 500')
@app.post('/api/downloads/{id}/cancel')
def cancel(id:int):
    if not downloader.cancel(id): raise HTTPException(409,'当前任务不能取消')
    return {'ok':True}
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
    if not downloader.retry(id): raise HTTPException(409,'当前任务不能重试')
    return {'ok':True,'resumed':resumed}

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
    if transcoder.current_id==int(x['id']): raise HTTPException(409,'视频正在优化，请等待完成或先取消流畅版生成')
    try: transcoder.cancel_smooth(int(x['id']))
    except Exception: pass
    removed=safe_unlink(x.get('file_path')); safe_unlink(x.get('thumb_path'))
    if x.get('smooth_path'): safe_unlink(x['smooth_path'])
    try: transcoder.delete_variants(Path(x.get('file_path') or ''), int(x['id']))
    except Exception: pass
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
    if any(x['id']==transcoder.current_id for x in rows): raise HTTPException(409,'选中的视频正在优化，请等待完成或先取消流畅版生成')
    removed=sum(delete_media_record(x) for x in rows)
    return {'deleted':len(rows),'bytes':removed}
@app.get('/api/media/download-zip')
def download_zip(ids:str=''):
    wanted=[]
    for part in (ids or '').split(','):
        part=part.strip()
        if part.isdigit(): wanted.append(int(part))
    if not wanted: raise HTTPException(400,'请选择要下载的视频')
    if len(wanted)>200: raise HTTPException(400,'一次最多打包下载 200 个视频')
    rows=db.all('SELECT * FROM media WHERE id IN ('+','.join('?' for _ in wanted)+')',tuple(dict.fromkeys(wanted)))
    if not rows: raise HTTPException(404,'没有找到可下载的视频')
    items=[]
    for x in rows:
        p=Path(x['file_path']).resolve()
        if ROOT not in p.parents or not p.is_file(): continue
        items.append((x['file_name'],p))
    if not items: raise HTTPException(404,'视频文件不存在')
    name=f"telegram-videos-{now()[:10]}.zip"
    return StreamingResponse(zip_media_files(items),media_type='application/zip',headers={
        'Content-Disposition':f"attachment; filename*=UTF-8''{quote(name)}",
        'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
@app.get('/api/media/{id}/smooth')
def smooth_status(id:int):
    x=db.one('SELECT id,smooth_status,smooth_progress,smooth_error,smooth_size,smooth_path FROM media WHERE id=?',(id,))
    if not x: raise HTTPException(404,'视频不存在')
    ready=bool(x['smooth_path'] and Path(x['smooth_path']).is_file() and x['smooth_status']=='ready')
    status='ready' if ready else x['smooth_status']
    return {'id':x['id'],'status':status,'progress':float(x['smooth_progress'] or 0),
            'error':x['smooth_error'] or '','size':int(x['smooth_size'] or 0),'ready':ready}
@app.post('/api/media/{id}/smooth')
def start_smooth(id:int):
    x,p=media_row(id)
    try: transcoder.enqueue_smooth(id)
    except ValueError as exc: raise HTTPException(409,str(exc)) from None
    return smooth_status(id)
@app.delete('/api/media/{id}/smooth')
def remove_smooth(id:int):
    x=db.one('SELECT * FROM media WHERE id=?',(id,))
    if not x: raise HTTPException(404,'视频不存在')
    transcoder.cancel_smooth(id)
    if x.get('smooth_path'): safe_unlink(x['smooth_path'])
    db.execute("UPDATE media SET smooth_path='',smooth_status='idle',smooth_progress=0,smooth_size=0,smooth_error='已移除流畅版' WHERE id=?",(id,))
    return {'ok':True}
@app.get('/api/media/{id}')
def media_detail(id:int): return media_row(id)[0]
@app.get('/api/media/{id}/sendability')
async def media_sendability(id:int):
    x,_=media_row(id); return await tg.media_sendability(int(x.get('account_id') or 1),x)

@app.get('/api/media/{id}/playback')
def playback(id:int):
    x,_=media_row(id)
    ready=x['original_hls_status']=='ready' and (transcoder.original_directory(id)/'index.m3u8').is_file()
    return {'original':{'type':'hls' if ready else 'file',
            'url':f'/api/media/{id}/hls/v2/index.m3u8' if ready else f'/api/media/{id}/stream?quality=original'},
            'status':x['original_hls_status']}

@app.get('/api/media/{id}/preview')
def seek_preview(id:int):
    x,_=media_row(id)
    index=transcoder.preview_directory(id)/'index.json'
    if x['preview_status']!='ready' or not index.is_file():
        return {'status':x['preview_status']}
    data=json.loads(index.read_text())
    data['sheets']=[f'/api/media/{id}/preview/{name}' for name in data['sheets']]
    return {'status':'ready',**data}

@app.get('/api/media/{id}/preview/{name}')
def seek_preview_sheet(id:int,name:str):
    x,_=media_row(id)
    if x['preview_status']!='ready' or not re.fullmatch(r'sheet-[0-9]{3}\.jpg',name):
        raise HTTPException(404,'预览不存在')
    path=transcoder.preview_directory(id)/name
    if not path.is_file(): raise HTTPException(404,'预览不存在')
    return FileResponse(path,media_type='image/jpeg',headers={'X-Content-Type-Options':'nosniff'})

@app.get('/api/media/{id}/hls/v2/{name}')
def original_hls(id:int,name:str):
    x,_=media_row(id)
    if x['original_hls_status']!='ready' or not re.fullmatch(r'(?:index\.m3u8|init\.mp4|segment-[0-9]{5,}\.(?:m4s|ts))',name):
        raise HTTPException(404,'播放分片不存在')
    p=(transcoder.original_directory(id)/name).resolve()
    if MEDIA_ROOT not in p.parents or not p.is_file(): raise HTTPException(404,'播放分片不存在')
    mime='application/vnd.apple.mpegurl' if name.endswith('.m3u8') else ('video/mp2t' if name.endswith('.ts') else 'video/mp4')
    headers={'Cache-Control':'private, max-age=3600'}
    if os.getenv('USE_X_ACCEL','false').lower()=='true':
        headers['X-Accel-Redirect']='/protected-media/'+quote(p.relative_to(MEDIA_ROOT).as_posix(),safe='/')
        return Response(media_type=mime,headers=headers)
    return FileResponse(p,media_type=mime,headers=headers)
@app.get('/api/media/{id}/thumbnail')
def thumbnail(id:int):
    x,_=media_row(id); p=Path(x['thumb_path']).resolve() if x['thumb_path'] else None
    if not p or ROOT not in p.parents or not p.is_file(): raise HTTPException(404,'无缩略图')
    return FileResponse(p,media_type='image/jpeg')
@app.get('/api/media/{id}/stream')
def stream(id:int,request:Request,download:bool=False,quality:str='original'):
    x,p=media_row(id); filename=x['file_name']; mime=x['mime']
    if quality=='smooth':
        smooth=Path(x.get('smooth_path') or '')
        if x.get('smooth_status')!='ready' or not smooth.is_file(): raise HTTPException(409,'流畅版尚未生成完成')
        p=smooth.resolve(); mime='video/mp4'; filename=Path(filename).stem+' - 流畅480p.mp4'
        if ROOT not in p.parents: raise HTTPException(404,'视频文件不存在')
    size=p.stat().st_size; rng=request.headers.get('range')
    # Validate before X-Accel as well, so bad ranges get the same non-cacheable
    # response with or without Nginx acceleration.
    if rng:
        try:
            match=re.fullmatch(r'bytes=([0-9]*)-([0-9]*)',rng)
            if not match or size==0: raise ValueError()
            start_s,end_s=match.groups()
            if not start_s:
                suffix=int(end_s)
                if suffix<=0: raise ValueError()
                start=max(0,size-suffix); end=size-1
            else:
                start=int(start_s); end=min(int(end_s),size-1) if end_s else size-1
                if start>=size or start>end: raise ValueError()
        except ValueError: return Response(status_code=416,headers={'Content-Range':f'bytes */{size}'})
    headers={'Accept-Ranges':'bytes','Cache-Control':'private, max-age=3600','Content-Disposition':('attachment' if download else 'inline')+f"; filename*=UTF-8''{quote(filename)}"}
    if os.getenv('USE_X_ACCEL','false').lower()=='true' and MEDIA_ROOT in p.parents:
        relative=quote(p.relative_to(MEDIA_ROOT).as_posix(),safe='/')
        headers['X-Accel-Redirect']='/protected-media/'+relative
        return Response(media_type=mime,headers=headers)
    if not rng: return FileResponse(p,media_type=mime,headers=headers)
    def iterator():
        with p.open('rb') as f:
            f.seek(start); remain=end-start+1
            while remain:
                chunk=f.read(min(1024*1024,remain))
                if not chunk: break
                remain-=len(chunk); yield chunk
    headers.update({'Content-Range':f'bytes {start}-{end}/{size}','Content-Length':str(end-start+1)})
    return StreamingResponse(iterator(),status_code=206,media_type=mime,headers=headers)
class Rename(BaseModel): name:str=Field(min_length=1,max_length=240)
@app.patch('/api/media/{id}')
def rename(id:int,b:Rename):
    x,p=media_row(id); name=Path(b.name).name
    if transcoder.current_id==id: raise HTTPException(409,'视频正在优化，请等待完成后重命名')
    if name!=b.name or name in ('.','..'): raise HTTPException(400,'文件名不合法')
    new=p.with_name(f"{x['message_id']}_{name}")
    if new.exists() and new!=p: raise HTTPException(409,'同名文件已存在')
    p.rename(new)
    smooth=x.get('smooth_path') or ''
    if smooth:
        old_smooth=Path(smooth)
        if old_smooth.is_file():
            new_smooth=new.with_name(new.stem+'.smooth.mp4')
            try:
                old_smooth.replace(new_smooth)
                db.execute('UPDATE media SET smooth_path=? WHERE id=?',(str(new_smooth),id))
            except OSError: pass
    db.execute('UPDATE media SET file_name=?,file_path=? WHERE id=?',(name,str(new),id)); return {'ok':True}
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
