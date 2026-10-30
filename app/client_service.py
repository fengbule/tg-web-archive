"""Account-scoped Telegram client actions. No message history is stored locally."""
import asyncio
import base64
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from telethon import utils
from telethon.errors import InviteRequestSentError, UserAlreadyParticipantError
from telethon.tl import functions, types


def parse_target(target):
    value=target.strip()
    if value.startswith(('https://','http://')):
        url=urlparse(value)
        if url.hostname not in ('t.me','www.t.me','telegram.me'): raise ValueError('请使用 Telegram 官方链接或 @用户名')
        value=url.path.strip('/')
    if value.startswith('joinchat/'): value='+'+value[9:]
    if value.startswith('+'):
        if not re.fullmatch(r'\+[A-Za-z0-9_-]{5,200}',value): raise ValueError('邀请链接格式不正确')
        return 'invite',value[1:]
    value=value.lstrip('@').split('/')[0]
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{3,31}',value): raise ValueError('请输入有效的 @用户名或 t.me 邀请链接')
    return 'public',value


class ClientActions:
    def client_summary(self,entity,**extra):
        kind=self._kind(entity); rights=getattr(entity,'admin_rights',None)
        admin=bool(getattr(entity,'creator',False) or rights)
        broadcast=kind=='channel'
        banned=getattr(entity,'banned_rights',None) or (None if admin else getattr(entity,'default_banned_rights',None))
        can_send=bool((not broadcast or getattr(entity,'creator',False) or getattr(rights,'post_messages',False))
                      and not getattr(banned,'send_messages',False) and not getattr(banned,'send_plain',False)
                      and not getattr(entity,'left',False) and not getattr(entity,'kicked',False))
        return {'peer_id':int(utils.get_peer_id(entity)),'title':self._entity_title(entity),
                'username':getattr(entity,'username',None),'kind':kind,'can_send':can_send,
                'can_leave':kind in ('channel','group') and not getattr(entity,'creator',False),
                'creator':bool(getattr(entity,'creator',False)),'member':not bool(getattr(entity,'left',False)),
                'account_id':self.account_id,**extra}

    async def client_dialogs(self,cursor='',limit=40,archived=False):
        c=await self.get_client(); kwargs={'limit':limit+1,'folder':1 if archived else 0,'ignore_migrated':True}
        if cursor:
            try:
                data=json.loads(base64.urlsafe_b64decode(cursor.encode()))
                if data['account']!=self.account_id or data['folder']!=int(archived): raise ValueError()
                kwargs.update(offset_date=datetime.fromisoformat(data['date']),offset_id=int(data['id']),
                              offset_peer=await c.get_input_entity(int(data['peer'])),ignore_pinned=True)
            except Exception: raise ValueError('会话分页已失效，请刷新列表') from None
        dialogs=[]
        async for d in c.iter_dialogs(**kwargs): dialogs.append(d)
        more=len(dialogs)>limit; dialogs=dialogs[:limit];items=[]
        for d in dialogs:
            items.append(self.client_summary(d.entity,unread_count=int(d.unread_count or 0),pinned=bool(d.pinned),
                archived=bool(d.folder_id),muted=bool(getattr(getattr(d.entity,'notify_settings',None),'silent',False)),
                last_message=(getattr(d.message,'message','') or '')[:160],last_date=d.date.isoformat() if d.date else None))
        next_cursor=None
        if more and dialogs and dialogs[-1].date:
            d=dialogs[-1]
            next_cursor=base64.urlsafe_b64encode(json.dumps({'account':self.account_id,'folder':int(archived),
                'date':d.date.isoformat(),'id':getattr(d.message,'id',0),'peer':int(d.id)}).encode()).decode()
        return {'items':items,'next_cursor':next_cursor,'account_id':self.account_id}

    async def client_info(self,peer_id):
        entity=await self._entity(peer_id); c=await self.get_client(); input_peer=await c.get_input_entity(entity)
        notify=await c(functions.account.GetNotifySettingsRequest(types.InputNotifyPeer(input_peer)))
        mute=getattr(notify,'mute_until',None)
        muted=bool(mute and (mute.timestamp() if isinstance(mute,datetime) else mute)>datetime.now(timezone.utc).timestamp())
        if isinstance(entity,types.InputPeerSelf):entity=await self._me()
        return self.client_summary(entity,muted=muted)

    async def client_messages(self,peer_id,offset_id=0,after_id=0,limit=40,query=''):
        c=await self.get_client(); entity=await self._entity(peer_id);kwargs={'limit':limit+1}
        if query: kwargs['search']=query
        if after_id: kwargs.update(min_id=after_id,reverse=True)
        else: kwargs['offset_id']=offset_id
        items=[]
        async for m in c.iter_messages(entity,**kwargs): items.append(await self._message_dict(m,peer_id))
        more=len(items)>limit;items=items[:limit]
        if not after_id:items.reverse()
        return {'items':items,'has_more':more,'next_offset_id':items[0]['id'] if more and items and not after_id else None,
                'account_id':self.account_id}

    async def client_send(self,peer_id,text,reply_to=None,request_id=None):
        # Prevent repeated clicks/retries within this running account service.
        if not hasattr(self,'client_send_lock'):self.client_send_lock=asyncio.Lock();self.client_sent={}
        async with self.client_send_lock:
            signature=(peer_id,text,reply_to)
            if request_id in self.client_sent:
                old,result=self.client_sent[request_id]
                if signature!=old:raise ValueError('发送请求已使用，请重新提交')
                return result
            c=await self.get_client();entity=await self._entity(peer_id)
            m=await c.send_message(entity,text,reply_to=reply_to,parse_mode=None,link_preview=False)
            result=await self._message_dict(m,peer_id)
            if request_id:
                self.client_sent[request_id]=(signature,result)
                while len(self.client_sent)>128:self.client_sent.pop(next(iter(self.client_sent)))
            return result

    async def client_edit(self,peer_id,message_id,text):
        c=await self.get_client();entity=await self._entity(peer_id);m=await c.get_messages(entity,ids=message_id)
        if not m or not m.out:raise ValueError('只能编辑当前账号自己发送的消息')
        result=await c.edit_message(entity,message_id,text,parse_mode=None,link_preview=False)
        return await self._message_dict(result,peer_id)

    async def client_action(self,peer_id,action,enabled=True,max_id=0):
        c=await self.get_client();entity=await self._entity(peer_id);peer=await c.get_input_entity(entity)
        if action=='read':
            if max_id<=0:raise ValueError('没有可标记已读的消息')
            await c.send_read_acknowledge(entity,max_id=max_id)
        elif action=='pin':await c(functions.messages.ToggleDialogPinRequest(types.InputDialogPeer(peer),pinned=enabled))
        elif action=='archive':await c.edit_folder(entity,folder=1 if enabled else 0)
        elif action=='mute':
            await c(functions.account.UpdateNotifySettingsRequest(types.InputNotifyPeer(peer),
                types.InputPeerNotifySettings(mute_until=2147483647 if enabled else 0)))
        elif action=='leave':
            if not self.client_summary(entity)['can_leave']:raise ValueError('不能退出私聊、收藏夹或自己创建的频道/群组')
            await self.leave_dialog(peer_id)
        self.channels_cache=[];self.channels_cached_at=0
        return {'ok':True,'account_id':self.account_id}

    async def client_target(self,target,join=False):
        kind,value=parse_target(target);c=await self.get_client()
        try:
            if kind=='invite':
                preview=await c(functions.messages.CheckChatInviteRequest(value))
                entity=getattr(preview,'chat',None)
                if not join:
                    if entity:return self.client_summary(entity,invite=True,already_member=isinstance(preview,types.ChatInviteAlready))
                    return {'title':preview.title,'kind':'channel' if getattr(preview,'broadcast',False) else 'group',
                            'invite':True,'already_member':False,'request_needed':bool(getattr(preview,'request_needed',False)),
                            'participants_count':getattr(preview,'participants_count',0),'account_id':self.account_id}
                if isinstance(preview,types.ChatInviteAlready):return self.client_summary(entity,status='joined')
                updates=await c(functions.messages.ImportChatInviteRequest(value))
                entity=next(iter(getattr(updates,'chats',[]) or []),None)
                if entity is None:return {'status':'requested','title':preview.title,'account_id':self.account_id}
            else:
                entity=await c.get_entity(value)
                if join:
                    if isinstance(entity,types.Channel):
                        updates=await c(functions.channels.JoinChannelRequest(entity))
                        entity=next((chat for chat in (getattr(updates,'chats',[]) or []) if chat.id==entity.id),entity)
                        entity.left=False
                    elif isinstance(entity,types.User) and entity.bot:await c.send_message(entity,'/start',parse_mode=None)
                    else:raise ValueError('此目标是私聊，请打开对话；无需加入')
            if join:self.channels_cache=[];self.channels_cached_at=0
            return self.client_summary(entity,status='joined' if join else 'preview')
        except InviteRequestSentError:return {'status':'requested','title':'已申请加入，等待管理员批准','account_id':self.account_id}
        except UserAlreadyParticipantError:
            return {'status':'joined','title':'已在该频道或群组中','account_id':self.account_id}
