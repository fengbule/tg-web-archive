import asyncio
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace as NS

import pytest
from cryptography.fernet import Fernet
from telethon import utils
from telethon.tl import functions,types
from telethon.errors import InviteRequestSentError
from app.client_service import parse_target
from app.db import Database
from app.telegram_service import TelegramManager


@pytest.fixture
def client_service(tmp_path):
    db=Database(tmp_path/'db');db.init();svc=TelegramManager(tmp_path,tmp_path/'thumbs',db,Fernet(Fernet.generate_key())).service()
    group=types.Channel(id=11,title='Group',photo=types.ChatPhotoEmpty(),date=datetime.now(timezone.utc),megagroup=True)
    user=types.User(id=22,first_name='Friend');broadcast=types.Channel(id=33,title='Channel',photo=types.ChatPhotoEmpty(),date=group.date,broadcast=True)
    calls=[]
    class Client:
        async def get_me(self):return types.User(id=999,first_name='Me')
        entities={utils.get_peer_id(group):group,22:user,utils.get_peer_id(broadcast):broadcast,'news':broadcast}
        async def get_entity(self,p):return self.entities.get(p,group)
        async def get_input_entity(self,p):return types.InputPeerChannel(p.id,1) if isinstance(p,types.Channel) else types.InputPeerUser(22,1)
        async def __call__(self,r):
            calls.append(r)
            if isinstance(r,functions.account.GetNotifySettingsRequest):return NS(mute_until=datetime.now(timezone.utc)+timedelta(days=1))
            if isinstance(r,functions.messages.CheckChatInviteRequest):return NS(title='Private group',request_needed=True)
            if isinstance(r,functions.messages.ImportChatInviteRequest):raise InviteRequestSentError(request=r)
            return NS(chats=[group])
        async def iter_dialogs(self,**kwargs):
            calls.append(kwargs)
            for e in (group,user,broadcast):yield NS(entity=e,id=utils.get_peer_id(e),date=group.date,unread_count=2,pinned=False,folder_id=None,message=NS(id=e.id,message='hello'))
        async def iter_messages(self,entity,**kwargs):
            calls.append(kwargs)
            ids=range(1,5) if kwargs.get('reverse') else range(4,0,-1)
            for i in ids:yield message(i)
        async def send_message(self,entity,text,**kwargs):calls.append(('send',text,kwargs));await asyncio.sleep(.01);return message(10,text)
        async def get_messages(self,entity,ids):return message(ids,out=ids!=8)
        async def edit_message(self,entity,id,text,**kwargs):calls.append(('edit',kwargs));return message(id,text)
        async def send_read_acknowledge(self,entity,**kwargs):calls.append(('read',kwargs))
        async def edit_folder(self,entity,**kwargs):calls.append(('archive',kwargs))
        async def delete_dialog(self,entity):calls.append(('leave',entity.id))
    def message(id,text='hello',out=True):return NS(id=id,message=text,date=group.date,out=out,sender=user,reply_to_msg_id=None,file=None,buttons=None,edit_date=None)
    c=Client()
    async def get_client():return c
    svc.get_client=get_client
    yield svc,c,calls,group,user,broadcast
    db.close()


@pytest.mark.parametrize('text,expected', [('@news',('public','news')),('https://t.me/news/123',('public','news')),('https://t.me/+abc_DEF',('invite','abc_DEF')),('https://t.me/joinchat/abc_DEF',('invite','abc_DEF'))])
def test_target_parser(text,expected):assert parse_target(text)==expected

@pytest.mark.parametrize('target',['https://evil.example/t.me/news','abc','https://t.me/+bad!','javascript:alert(1)',''])
def test_reject_invalid_target(target):
    with pytest.raises(ValueError):parse_target(target)


def test_paging_permissions_and_cursor_account_scope(client_service):
    svc,c,calls,group,user,broadcast=client_service
    result=asyncio.run(svc.client_dialogs(limit=2));assert len(result['items'])==2 and result['next_cursor']
    asyncio.run(svc.client_dialogs(cursor=result['next_cursor'],limit=2));assert calls[-1]['ignore_pinned']
    with pytest.raises(ValueError):asyncio.run(svc.client_dialogs(cursor=result['next_cursor'],archived=True))
    svc.account_id=2
    with pytest.raises(ValueError):asyncio.run(svc.client_dialogs(cursor=result['next_cursor']))
    assert not svc.client_summary(broadcast)['can_send'];broadcast.creator=True
    assert svc.client_summary(broadcast)['can_send'] and not svc.client_summary(broadcast)['can_leave']
    broadcast.creator=False;broadcast.admin_rights=NS(post_messages=False)
    assert not svc.client_summary(broadcast)['can_send'],'unrelated admin rights must not imply posting permission'
    assert asyncio.run(svc.client_info(22))['muted']


def test_history_pagination_search_and_no_implicit_read(client_service):
    svc,c,calls,*_=client_service
    x=asyncio.run(svc.client_messages(22,limit=2,query='needle'));assert [m['id'] for m in x['items']]==[3,4] and x['next_offset_id']==3
    assert calls[-1]['search']=='needle';assert not any(isinstance(x,tuple) and x[0]=='read' for x in calls)
    x=asyncio.run(svc.client_messages(22,after_id=1,limit=2));assert [m['id'] for m in x['items']]==[1,2] and x['has_more']


def test_send_plaintext_reply_duplicate_and_edit_ownership(client_service):
    svc,c,calls,*_=client_service
    async def send():return await asyncio.gather(*(svc.client_send(22,'**literal**',3,'same-request') for _ in range(2)))
    result=asyncio.run(send());assert result[0]==result[1]
    sends=[x for x in calls if isinstance(x,tuple) and x[0]=='send'];assert len(sends)==1 and sends[0][2]['parse_mode'] is None and sends[0][2]['reply_to']==3
    with pytest.raises(ValueError):asyncio.run(svc.client_send(22,'different',3,'same-request'))
    with pytest.raises(ValueError):asyncio.run(svc.client_edit(22,8,'cannot edit others'))
    assert asyncio.run(svc.client_edit(22,9,'edited'))['text']=='edited'


def test_actions_no_user_leave_and_local_rows_untouched(client_service):
    svc,c,calls,group,*_=client_service
    for action in ('pin','mute','archive'):asyncio.run(svc.client_action(22,action,True))
    mute=next(r for r in calls if isinstance(r,functions.account.UpdateNotifySettingsRequest));assert mute.settings.mute_until==2147483647 and mute.settings.silent is None;bytes(mute)
    asyncio.run(svc.client_action(22,'read',max_id=123));assert calls[-1]==('read',{'max_id':123})
    with pytest.raises(ValueError):asyncio.run(svc.client_action(22,'leave'))
    async def me():return types.User(id=999,first_name='Me')
    svc._me=me;asyncio.run(svc.client_action(utils.get_peer_id(group),'leave'));assert calls[-1]==('leave',11)
    assert svc.db.one('SELECT count(*) n FROM accounts')['n']==1


def test_invite_preview_has_no_join_side_effect_and_pending_not_success(client_service):
    svc,c,calls,*_=client_service
    x=asyncio.run(svc.client_target('https://t.me/+abc_DEF'));assert x['request_needed'] and 'peer_id' not in x
    assert not any(isinstance(r,functions.messages.ImportChatInviteRequest) for r in calls)
    x=asyncio.run(svc.client_target('https://t.me/+abc_DEF',True));assert x['status']=='requested'
    c.entities['news'].left=True
    x=asyncio.run(svc.client_target('@news',True));assert x['status']=='joined' and x['member'] and not x['can_send']
