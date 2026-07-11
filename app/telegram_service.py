import asyncio, logging, time, uuid, os, re
from pathlib import Path
from telethon import TelegramClient
from telethon import utils
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PasswordHashInvalidError, FloodWaitError
from telethon.tl.types import Channel, Chat, User
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from .db import now

log=logging.getLogger('tvm.telegram')

class TelegramAccountService:
    def __init__(self,account_id:int,session_name:str,session_dir:Path,thumb_dir:Path,db,cipher):
        self.account_id=account_id; self.session_name=session_name; self.session_dir=session_dir; self.thumb_dir=thumb_dir
        self.db=db; self.cipher=cipher; self.client=None; self.phone=''; self.phone_code_hash=''; self.lock=asyncio.Lock(); self.channels_cache=[]; self.channels_cached_at=0; self.me_cache=None
    def _key(self,key): return key if self.account_id==1 else f'account:{self.account_id}:{key}'
    def _cfg(self,key):
        r=self.db.one('SELECT value FROM config WHERE key=?',(self._key(key),)); return r['value'] if r else None
    def save_api(self,api_id,api_hash):
        for k,v in [('api_id',str(api_id)),('api_hash',api_hash)]:
            enc=self.cipher.encrypt(v.encode()).decode(); self.db.execute('INSERT OR REPLACE INTO config(key,value) VALUES(?,?)',(self._key(k),enc))
    def api_configured(self): return bool(self._cfg('api_id') and self._cfg('api_hash'))
    def credentials(self): return int(self.cipher.decrypt(self._cfg('api_id').encode())),self.cipher.decrypt(self._cfg('api_hash').encode()).decode()
    async def get_client(self):
        async with self.lock:
            if self.client is None:
                if not self.api_configured(): raise RuntimeError('请先填写 Telegram API ID 和 API Hash')
                aid,ah=self.credentials(); self.client=TelegramClient(str(self.session_dir/self.session_name),aid,ah,sequential_updates=True)
                await self.client.connect()
            elif not self.client.is_connected(): await self.client.connect()
            return self.client
    async def _me(self):
        if getattr(self,'me_cache',None) is None:
            self.me_cache=await (await self.get_client()).get_me()
        return self.me_cache
    async def status(self):
        if not self.api_configured(): return {'configured':False,'authorized':False,'account_id':self.account_id}
        c=await self.get_client(); ok=await c.is_user_authorized(); result={'configured':True,'authorized':ok,'account_id':self.account_id}
        if ok:
            me=await self._me(); result['name']=' '.join(x for x in [me.first_name,me.last_name] if x); result['phone']='***'+(me.phone[-4:] if me.phone else '')
        return result
    async def send_code(self,phone,api_id=None,api_hash=None):
        if api_id and api_hash:
            if self.client: await self.client.disconnect(); self.client=None
            self.save_api(api_id,api_hash)
        c=await self.get_client(); sent=await c.send_code_request(phone); self.phone=phone; self.phone_code_hash=sent.phone_code_hash
    async def verify_code(self,code):
        c=await self.get_client()
        try: await c.sign_in(self.phone,code,phone_code_hash=self.phone_code_hash); return 'ok'
        except SessionPasswordNeededError: return 'password_needed'
        except PhoneCodeInvalidError: raise ValueError('验证码无效，请重新输入')
    async def verify_password(self,password):
        c=await self.get_client()
        try: await c.sign_in(password=password)
        except PasswordHashInvalidError: raise ValueError('两步验证密码错误')
    async def logout(self,clear=False):
        if self.client:
            try: await self.client.log_out()
            finally: await self.client.disconnect(); self.client=None
        if clear:
            for p in self.session_dir.glob(self.session_name+'.session*'): p.unlink(missing_ok=True)
        self.channels_cache=[]; self.me_cache=None
    async def disconnect(self):
        if self.client: await self.client.disconnect(); self.client=None
    async def channels(self,query='',refresh=False):
        if self.channels_cache and not refresh and time.monotonic()-self.channels_cached_at<300:
            return [x for x in self.channels_cache if not query or query.lower() in x['title'].lower()]
        c=await self.get_client(); out=[]
        async for d in c.iter_dialogs():
            if isinstance(d.entity,Channel): out.append({'id':d.entity.id,'title':d.name,'username':getattr(d.entity,'username',None),'photo':bool(d.entity.photo)})
        self.channels_cache=out; self.channels_cached_at=time.monotonic()
        return [x for x in out if not query or query.lower() in x['title'].lower()]
    async def videos(self,channel_id,offset_id=0,limit=30):
        c=await self.get_client(); entity=await c.get_entity(int(channel_id)); out=[]; last=0
        async for m in c.iter_messages(entity,limit=min(limit,50),offset_id=offset_id):
            last=m.id
            if not m.video: continue
            doc=m.video; attrs={type(a).__name__:a for a in doc.attributes}; va=attrs.get('DocumentAttributeVideo'); fa=attrs.get('DocumentAttributeFilename')
            name=getattr(fa,'file_name',None) or f'video_{m.id}.mp4'
            out.append({'message_id':m.id,'channel_id':int(channel_id),'channel_title':getattr(entity,'title',''),'file_name':name,
              'caption':m.message or '','date':m.date.isoformat(),'size':doc.size or 0,'duration':getattr(va,'duration',0) or 0,
              'width':getattr(va,'w',0) or 0,'height':getattr(va,'h',0) or 0,'has_thumbnail':bool(getattr(doc,'thumbs',None))})
        existing={x['message_id'] for x in self.db.all('SELECT message_id FROM media WHERE account_id=? AND channel_id=?',(self.account_id,int(channel_id)))}
        for x in out: x['downloaded']=x['message_id'] in existing
        return {'items':out,'next_offset_id':last or None}
    async def thumbnail(self,channel_id,message_id):
        target=self.thumb_dir/str(self.account_id)/str(channel_id)/f'{message_id}.jpg'
        if target.is_file() and target.stat().st_size: return target
        target.parent.mkdir(parents=True,exist_ok=True); temp=target.with_suffix('.part')
        c=await self.get_client(); entity=await c.get_entity(int(channel_id)); msg=await c.get_messages(entity,ids=int(message_id))
        if not msg or not msg.video or not getattr(msg.video,'thumbs',None): return None
        try:
            result=await c.download_media(msg.video,file=str(temp),thumb=-1)
            p=Path(result) if result else temp
            if p.is_file() and p.stat().st_size:
                os.replace(p,target); return target
        finally: temp.unlink(missing_ok=True)
        return None
    async def _entity(self,peer_id):
        c=await self.get_client()
        me=await self._me()
        if int(peer_id)==int(utils.get_peer_id(me)):
            return await c.get_input_entity('me')
        try: return await c.get_entity(int(peer_id))
        except Exception:
            async for d in c.iter_dialogs():
                if int(d.id)==int(peer_id) or int(getattr(d.entity,'id',0))==abs(int(peer_id)): return d.entity
            raise ValueError('找不到这个会话，请刷新会话列表后重试')
    @staticmethod
    def _entity_title(entity):
        if isinstance(entity,User): return ' '.join(x for x in (entity.first_name,entity.last_name) if x) or getattr(entity,'username',None) or '未命名用户'
        return getattr(entity,'title',None) or getattr(entity,'username',None) or '未命名会话'
    @staticmethod
    def _kind(entity):
        if isinstance(entity,User): return 'bot' if entity.bot else 'user'
        if isinstance(entity,Channel): return 'group' if entity.megagroup else 'channel'
        return 'group' if isinstance(entity,Chat) else 'unknown'
    async def dialogs(self,query='',limit=100):
        c=await self.get_client(); out=[]; q=query.strip().lower()
        async for d in c.iter_dialogs(limit=min(max(limit,1),200)):
            entity=d.entity; title=self._entity_title(entity); username=getattr(entity,'username',None)
            if q and q not in title.lower() and q not in (username or '').lower(): continue
            kind=self._kind(entity)
            can_send=not (kind=='channel' and not (getattr(entity,'creator',False) or getattr(entity,'admin_rights',None)))
            out.append({'peer_id':int(d.id),'title':title,'username':username,'kind':kind,'unread_count':int(d.unread_count or 0),
                        'pinned':bool(d.pinned),'archived':bool(d.folder_id),'can_send':can_send,'photo':bool(getattr(entity,'photo',None)),
                        'last_message':(d.message.message or '')[:120] if d.message else '',
                        'last_date':d.date.isoformat() if d.date else None})
        return out
    async def saved_messages(self):
        me=await self._me()
        return {'peer_id':int(utils.get_peer_id(me)),'title':'收藏夹','username':getattr(me,'username',None),
                'kind':'user','unread_count':0,'can_send':True,'is_self':True}
    async def _message_dict(self,m,peer_id=None):
        sender=getattr(m,'sender',None)
        if sender is None:
            try: sender=await m.get_sender()
            except Exception: sender=None
        buttons=[]
        try:
            for ri,row in enumerate(m.buttons or []):
                buttons.append([{'text':b.text,'row':ri,'col':ci,'url':getattr(b,'url',None)} for ci,b in enumerate(row)])
        except Exception: buttons=[]
        file=getattr(m,'file',None); media=None
        if file:
            media={'name':getattr(file,'name',None) or f'文件_{m.id}','size':int(getattr(file,'size',0) or 0),
                   'mime':getattr(file,'mime_type',None) or 'application/octet-stream'}
            if m.out and peer_id is not None:
                local=self.db.one("SELECT media_id FROM outbox WHERE account_id=? AND peer_id=? AND telegram_message_id=? AND status='completed' ORDER BY id DESC LIMIT 1",(self.account_id,int(peer_id),int(m.id)))
                if local: media['local_media_id']=int(local['media_id'])
        return {'id':int(m.id),'text':m.message or '','date':m.date.isoformat() if m.date else None,'out':bool(m.out),
                'sender':self._entity_title(sender) if sender else '未知发送者','reply_to_id':int(m.reply_to_msg_id) if m.reply_to_msg_id else None,
                'media':media,'buttons':buttons,'edited':bool(m.edit_date)}
    async def messages(self,peer_id,offset_id=0,after_id=0,limit=40):
        c=await self.get_client(); entity=await self._entity(peer_id); items=[]; limit=min(max(limit,1),80)
        if after_id:
            async for m in c.iter_messages(entity,min_id=int(after_id),reverse=True,limit=limit): items.append(await self._message_dict(m,peer_id))
        else:
            async for m in c.iter_messages(entity,offset_id=int(offset_id),limit=limit): items.append(await self._message_dict(m,peer_id))
            items.reverse()
            try: await c.send_read_acknowledge(entity)
            except Exception: pass
        return {'items':items,'next_offset_id':items[0]['id'] if items and not after_id else None}
    async def send_text(self,peer_id,text,reply_to=None):
        text=text.strip()
        if not text: raise ValueError('消息内容不能为空')
        if len(text)>4096: raise ValueError('单条消息不能超过 4096 个字符')
        c=await self.get_client(); entity=await self._entity(peer_id)
        try: m=await c.send_message(entity,text,reply_to=reply_to or None)
        except FloodWaitError as e: raise ValueError(f'Telegram 操作过于频繁，请等待 {e.seconds} 秒后重试')
        return await self._message_dict(m)
    async def delete_message(self,peer_id,message_id):
        c=await self.get_client(); entity=await self._entity(peer_id); m=await c.get_messages(entity,ids=int(message_id))
        if not m or not m.out: raise ValueError('只能删除当前账号自己发送的消息')
        await c.delete_messages(entity,[int(message_id)],revoke=True)
    async def click_button(self,peer_id,message_id,row,col):
        c=await self.get_client(); entity=await self._entity(peer_id); m=await c.get_messages(entity,ids=int(message_id))
        if not m: raise ValueError('消息已不存在')
        result=await m.click(int(row),int(col))
        answer=getattr(result,'message',None) or ''
        return {'answer':answer}
    async def resolve_target(self,target):
        c=await self.get_client(); value=target.strip()
        if not value: raise ValueError('请输入用户名或 Telegram 链接')
        invite=re.search(r'(?:joinchat/|t\.me/\+)([A-Za-z0-9_-]+)',value)
        if invite: return {'invite':True,'title':'私有邀请链接','target':value}
        value=re.sub(r'^https?://(?:www\.)?t\.me/','',value,flags=re.I).split('?',1)[0].strip('/').lstrip('@')
        try: entity=await c.get_entity(value)
        except Exception: raise ValueError('没有找到该用户、机器人、频道或群组')
        return {'invite':False,'peer_id':int(utils.get_peer_id(entity)),'title':self._entity_title(entity),'username':getattr(entity,'username',None),'kind':self._kind(entity),'target':target}
    async def join_target(self,target):
        c=await self.get_client(); value=target.strip(); invite=re.search(r'(?:joinchat/|t\.me/\+)([A-Za-z0-9_-]+)',value)
        try:
            if invite:
                updates=await c(ImportChatInviteRequest(invite.group(1))); chats=getattr(updates,'chats',[]) or []
                entity=chats[0] if chats else None
            else:
                value=re.sub(r'^https?://(?:www\.)?t\.me/','',value,flags=re.I).split('?',1)[0].strip('/').lstrip('@')
                entity=await c.get_entity(value)
                if isinstance(entity,(Channel,Chat)): await c(JoinChannelRequest(entity))
                elif isinstance(entity,User) and entity.bot: await c.send_message(entity,'/start')
                else: raise ValueError('这个目标不是可加入的频道、群组或机器人')
        except FloodWaitError as e: raise ValueError(f'Telegram 操作过于频繁，请等待 {e.seconds} 秒后重试')
        self.channels_cache=[]
        return {'title':self._entity_title(entity) if entity else '已加入','peer_id':int(utils.get_peer_id(entity)) if entity else None}
    async def leave_dialog(self,peer_id):
        c=await self.get_client(); me=await self._me()
        if int(peer_id)==int(utils.get_peer_id(me)): raise ValueError('收藏夹不能退出')
        entity=await self._entity(peer_id)
        if isinstance(entity,User): raise ValueError('私聊不能“退出”，可以直接删除自己发送的消息')
        await c.delete_dialog(entity); self.channels_cache=[]
    async def media_sendability(self,media):
        try:
            service_account=int(media.get('account_id') or self.account_id)
            if service_account!=self.account_id: return await self.db_manager.service(service_account).media_sendability(media)
            entity=await self._entity(media['channel_id'])
            c=await self.get_client(); message=await c.get_messages(entity,ids=int(media['message_id']))
            protected=bool(getattr(entity,'noforwards',False) or getattr(message,'noforwards',False))
            if protected: return {'allowed':False,'reason':'Telegram 原消息启用了内容保护，不能重新上传'}
            return {'allowed':True,'reason':''}
        except Exception:
            return {'allowed':False,'reason':'无法确认 Telegram 原消息的发送权限，请稍后重试'}
    async def source_is_protected(self,media): return not (await self.media_sendability(media))['allowed']
    async def send_file(self,peer_id,path,caption='',progress_callback=None):
        c=await self.get_client(); entity=await self._entity(peer_id)
        return await c.send_file(entity,str(path),caption=caption or '',supports_streaming=True,progress_callback=progress_callback)

class TelegramManager:
    def __init__(self,session_dir:Path,thumb_dir:Path,db,cipher):
        self.session_dir=session_dir; self.thumb_dir=thumb_dir; self.db=db; self.cipher=cipher; self.services={}
    @property
    def active_id(self):
        r=self.db.one("SELECT value FROM config WHERE key='active_account_id'")
        try: aid=int(r['value']) if r else 1
        except Exception: aid=1
        return aid if self.db.one('SELECT 1 x FROM accounts WHERE id=?',(aid,)) else 1
    def service(self,account_id=None):
        aid=int(account_id or self.active_id); row=self.db.one('SELECT * FROM accounts WHERE id=?',(aid,))
        if not row: raise ValueError('Telegram 账号不存在')
        if aid not in self.services:
            self.services[aid]=TelegramAccountService(aid,row['session_name'],self.session_dir,self.thumb_dir,self.db,self.cipher)
            self.services[aid].db_manager=self
        return self.services[aid]
    async def get_client(self,account_id=None): return await self.service(account_id).get_client()
    async def status(self): return await self.service().status()
    async def send_code(self,*a,**kw): return await self.service().send_code(*a,**kw)
    async def verify_code(self,*a,**kw): return await self.service().verify_code(*a,**kw)
    async def verify_password(self,*a,**kw): return await self.service().verify_password(*a,**kw)
    async def logout(self,*a,**kw): return await self.service().logout(*a,**kw)
    async def channels(self,*a,**kw): return await self.service().channels(*a,**kw)
    async def videos(self,*a,**kw): return await self.service().videos(*a,**kw)
    async def thumbnail(self,*a,**kw): return await self.service().thumbnail(*a,**kw)
    async def dialogs(self,*a,**kw): return await self.service().dialogs(*a,**kw)
    async def saved_messages(self): return await self.service().saved_messages()
    async def messages(self,*a,**kw): return await self.service().messages(*a,**kw)
    async def send_text(self,*a,**kw): return await self.service().send_text(*a,**kw)
    async def delete_message(self,*a,**kw): return await self.service().delete_message(*a,**kw)
    async def click_button(self,*a,**kw): return await self.service().click_button(*a,**kw)
    async def resolve_target(self,*a,**kw): return await self.service().resolve_target(*a,**kw)
    async def join_target(self,*a,**kw): return await self.service().join_target(*a,**kw)
    async def leave_dialog(self,*a,**kw): return await self.service().leave_dialog(*a,**kw)
    async def source_is_protected(self,account_id,media): return await self.service(account_id).source_is_protected(media)
    async def media_sendability(self,account_id,media): return await self.service(account_id).media_sendability(media)
    async def send_file(self,account_id,*a,**kw): return await self.service(account_id).send_file(*a,**kw)
    def list_accounts(self):
        rows=self.db.all('SELECT id,label,session_name,created_at FROM accounts ORDER BY id'); active=self.active_id
        for x in rows: x['active']=x['id']==active; x['configured']=self.service(x['id']).api_configured(); x['session_exists']=(self.session_dir/(x['session_name']+'.session')).exists()
        return rows
    def create_account(self,label):
        source=self.service(); name='account_'+uuid.uuid4().hex[:12]; cur=self.db.execute('INSERT INTO accounts(label,session_name,created_at) VALUES(?,?,?)',(label.strip() or '新账号',name,now())); aid=cur.lastrowid
        if source.api_configured():
            for key in ('api_id','api_hash'):
                self.db.execute('INSERT OR REPLACE INTO config(key,value) VALUES(?,?)',(f'account:{aid}:{key}',source._cfg(key)))
        return aid
    def activate(self,account_id):
        if not self.db.one('SELECT 1 x FROM accounts WHERE id=?',(account_id,)): raise ValueError('Telegram 账号不存在')
        self.db.execute("INSERT OR REPLACE INTO config(key,value) VALUES('active_account_id',?)",(str(account_id),))
    async def remove(self,account_id):
        rows=self.db.all('SELECT id FROM accounts');
        if len(rows)<=1: raise ValueError('至少保留一个 Telegram 账号')
        svc=self.service(account_id); await svc.logout(clear=True); self.services.pop(account_id,None)
        self.db.execute("DELETE FROM config WHERE key LIKE ?",(f'account:{account_id}:%',))
        if account_id==1:
            self.db.execute("DELETE FROM config WHERE key IN ('api_id','api_hash')")
        self.db.execute('DELETE FROM accounts WHERE id=?',(account_id,))
        if self.active_id==account_id: self.activate(next(x['id'] for x in rows if x['id']!=account_id))
    async def disconnect_all(self): await asyncio.gather(*(x.disconnect() for x in self.services.values()),return_exceptions=True)
