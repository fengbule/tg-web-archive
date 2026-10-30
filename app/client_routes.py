import asyncio
from uuid import UUID
from typing import Literal
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from telethon.errors import FloodWaitError, RPCError


def install_client_routes(app,tg):
    router=APIRouter(prefix='/api/client')
    async def call(account_id,method,*args,**kwargs):
        try:service=tg.service(account_id)
        except ValueError:raise HTTPException(404,'Telegram 账号不存在') from None
        try:return await asyncio.wait_for(getattr(service,method)(*args,**kwargs),timeout=40)
        except FloodWaitError as e:raise HTTPException(429,f'Telegram 操作频繁，请等待 {e.seconds} 秒后重试',headers={'Retry-After':str(e.seconds)}) from None
        except ValueError as e:raise HTTPException(400,str(e)) from None
        except TimeoutError:raise HTTPException(504,'Telegram 响应超时；发送结果可能已提交，请先刷新消息确认') from None
        except RPCError as e:
            name=type(e).__name__
            if name in ('ChatWriteForbiddenError','ChatAdminRequiredError','UserBannedInChannelError','ChatSendPlainForbiddenError','MessageAuthorRequiredError'):
                raise HTTPException(403,'当前账号没有执行此操作的 Telegram 权限') from None
            if name in ('InviteHashExpiredError','InviteHashInvalidError','UsernameInvalidError','UsernameNotOccupiedError','ChannelPrivateError'):
                raise HTTPException(404,'目标不可访问、用户名不存在或邀请已失效') from None
            if name=='MessageNotModifiedError':raise HTTPException(409,'消息内容未改变') from None
            raise HTTPException(409,'Telegram 未接受此操作，请检查账号权限、消息状态或加入限制') from None
        except (ConnectionError,OSError):raise HTTPException(502,'无法连接 Telegram，请稍后重试') from None

    @router.get('/dialogs')
    async def dialogs(account_id:int=Query(gt=0),cursor:str=Query(default='',max_length=1000),limit:int=Query(default=40,ge=1,le=80),archived:bool=False):
        return await call(account_id,'client_dialogs',cursor,limit,archived)
    @router.get('/dialogs/{peer_id}')
    async def info(peer_id:int,account_id:int=Query(gt=0)):return await call(account_id,'client_info',peer_id)
    @router.get('/dialogs/{peer_id}/messages')
    async def messages(peer_id:int,account_id:int=Query(gt=0),offset_id:int=Query(default=0,ge=0),after_id:int=Query(default=0,ge=0),limit:int=Query(default=40,ge=1,le=80),q:str=Query(default='',max_length=200)):
        return await call(account_id,'client_messages',peer_id,offset_id,after_id,limit,q.strip())
    @router.post('/dialogs/{peer_id}/messages')
    async def send(peer_id:int,b:ClientMessage,account_id:int=Query(gt=0)):
        return await call(account_id,'client_send',peer_id,b.text,b.reply_to,str(b.request_id))
    @router.patch('/dialogs/{peer_id}/messages/{message_id}')
    async def edit(peer_id:int,message_id:int,b:ClientEdit,account_id:int=Query(gt=0)):
        return await call(account_id,'client_edit',peer_id,message_id,b.text)
    @router.delete('/dialogs/{peer_id}/messages/{message_id}')
    async def delete(peer_id:int,message_id:int,account_id:int=Query(gt=0)):
        await call(account_id,'delete_message',peer_id,message_id);return {'ok':True}
    @router.post('/dialogs/{peer_id}/actions')
    async def action(peer_id:int,b:ClientAction,account_id:int=Query(gt=0)):
        return await call(account_id,'client_action',peer_id,b.action,b.enabled,b.max_id)
    @router.post('/dialogs/{peer_id}/messages/{message_id}/click')
    async def click(peer_id:int,message_id:int,b:ClientButton,account_id:int=Query(gt=0)):
        return await call(account_id,'click_button',peer_id,message_id,b.row,b.col)
    @router.post('/target/preview')
    async def preview(b:ClientTarget,account_id:int=Query(gt=0)):return await call(account_id,'client_target',b.target)
    @router.post('/target/join')
    async def join(b:ClientTarget,account_id:int=Query(gt=0)):return await call(account_id,'client_target',b.target,True)
    app.include_router(router)


class ClientEdit(BaseModel):
    text:str=Field(min_length=1,max_length=4096)
    @field_validator('text')
    @classmethod
    def text_not_blank(cls,value):
        if not value.strip():raise ValueError('消息不能为空')
        if len(value.encode('utf-16-le'))//2>4096:raise ValueError('消息超过 Telegram 长度限制')
        return value
class ClientMessage(ClientEdit):
    reply_to:int|None=Field(default=None,gt=0)
    request_id:UUID
class ClientAction(BaseModel):
    action:Literal['read','pin','archive','mute','leave']
    enabled:bool=True
    max_id:int=Field(default=0,ge=0)
class ClientTarget(BaseModel):target:str=Field(min_length=1,max_length=300)
class ClientButton(BaseModel):
    row:int=Field(ge=0,le=20)
    col:int=Field(ge=0,le=20)
