import json
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from telethon.crypto import AuthKey
from telethon.sessions import SQLiteSession, StringSession

from app.account_backup import collect_accounts, decrypt_backup, encrypt_backup, restore_accounts
from app.db import Database
from app.telegram_service import TelegramManager

PASSWORD = 'disposable-backup-password'


def manager(root):
    root.mkdir(); (root/'session').mkdir()
    db = Database(root/'app.db'); db.init()
    return TelegramManager(root/'session',root/'thumbs',db,Fernet(Fernet.generate_key()))


def authorize(tg):
    tg.service().save_api(123456,'a'*32,test_mode=True)
    path=tg.session_dir/'account.session'
    state=SQLiteSession(str(path))
    state.set_dc(2,'149.154.167.40',443); state.auth_key=AuthKey(b'x'*256)
    state.save(); state.close()


def test_portable_backup_new_key_duplicate_skip_and_no_live_client(tmp_path):
    source=manager(tmp_path/'source'); target=manager(tmp_path/'target')
    try:
        authorize(source)
        payload=collect_accounts(source)
        raw=encrypt_backup(payload,PASSWORD)
        assert b'x'*40 not in raw and b'a'*32 not in raw and b'149.154' not in raw
        rows=decrypt_backup(raw,PASSWORD)
        result=restore_accounts(target,rows)
        assert result['imported']==1 and result['skipped']==0
        aid=result['account_ids'][0]
        assert target.service(aid).credentials()==(123456,'a'*32)
        assert target.service(aid)._cfg('api_test_mode')=='1'
        assert target.active_id==1 and target.service(aid).client is None
        import asyncio
        listed=asyncio.run(target.list_accounts())
        assert listed[1]['restore_pending'] and listed[1]['status']=='restored'
        assert target.service(aid).client is None
        target.activate(aid)
        assert target.service(aid)._cfg('restore_pending') is None
        restored=collect_accounts(target,[aid])['accounts'][0]
        assert StringSession(restored['session']).auth_key.key==b'x'*256
        assert restore_accounts(target,rows)['skipped']==1
        assert len(target.db.all('SELECT * FROM accounts'))==2
        assert (source.session_dir/'account.session').is_file()
    finally:
        source.db.close(); target.db.close()


@pytest.mark.parametrize('change',['password','tamper','format','salt','oversize','bad-session'])
def test_bad_backups_rejected_before_any_mutation(tmp_path,change):
    tg=manager(tmp_path/'source')
    try:
        authorize(tg); payload=collect_accounts(tg)
        if change=='bad-session': payload['accounts'][0]['session']='1invalid'
        raw=encrypt_backup(payload,PASSWORD); password=PASSWORD
        if change=='password': password='wrong-password-long'
        elif change=='tamper':
            data=json.loads(raw); data['data']=data['data'][:-4]+'aaaa'; raw=json.dumps(data).encode()
        elif change=='format':
            data=json.loads(raw); data['format']='unknown'; raw=json.dumps(data).encode()
        elif change=='salt':
            data=json.loads(raw); data['salt']='eA=='; raw=json.dumps(data).encode()
        elif change=='oversize': raw=b'x'*(2*1024*1024+1)
        with pytest.raises(ValueError): decrypt_backup(raw,password)
        assert len(tg.db.all('SELECT * FROM accounts'))==1
    finally: tg.db.close()


def test_empty_slot_and_unknown_id(tmp_path):
    tg=manager(tmp_path/'source')
    try:
        rows=decrypt_backup(encrypt_backup(collect_accounts(tg),PASSWORD),PASSWORD)
        assert restore_accounts(tg,rows)['imported']==1
        assert not tg.service(2).api_configured()
        with pytest.raises(ValueError): collect_accounts(tg,[999])
    finally: tg.db.close()


def test_restore_rolls_back_files_and_accounts_on_failure(tmp_path,monkeypatch):
    import app.account_backup as backup
    tg=manager(tmp_path/'source'); target=manager(tmp_path/'target')
    try:
        authorize(tg); rows=collect_accounts(tg)['accounts']; rows.append({**rows[0],'session':None})
        real=target.cipher
        class Fails:
            calls=0
            def encrypt(self,value):
                self.calls+=1
                if self.calls==3: raise OSError('fixture failure')
                return real.encrypt(value)
        target.cipher=Fails()
        with pytest.raises(OSError): restore_accounts(target,rows)
        assert len(target.db.all('SELECT * FROM accounts'))==1
        assert not list(target.session_dir.iterdir())
        assert not target.db.all('SELECT * FROM config')
    finally: tg.db.close(); target.db.close()
