import asyncio
from collections import defaultdict
from contextlib import aclosing
from datetime import datetime,timezone
import logging
from types import SimpleNamespace

import pytest
from telethon.errors import FileMigrateError
from telethon.tl.types import Document
from app.download_connections import DownloadConnections,DownloadClient,create_sender
from app.parallel_download import iter_file,PART_SIZE


class Sender:
    def __init__(self,dc):self.dc=dc;self.closed=False
    async def disconnect(self):self.closed=True


class Client:
    def __init__(self,data,migrate=False):
        self.data=data;self.migrate=migrate;self.session=SimpleNamespace(dc_id=5)
        self._log=defaultdict(lambda:logging.getLogger('test'));self._sender=Sender(5)
        self.native=[];self.native_returns=[]
    async def _call(self,sender,request):
        assert not sender.closed
        if self.migrate and sender.dc==1:raise FileMigrateError(request,capture=2)
        await asyncio.sleep(.001 if request.offset%3 else .003)
        return SimpleNamespace(bytes=self.data[request.offset:request.offset+request.limit])
    async def _borrow_exported_sender(self,dc):
        sender=Sender(dc);self.native.append(sender);return sender
    async def _return_exported_sender(self,sender):
        self.native_returns.append(sender);await sender.disconnect()


def document(data):
    return Document(id=1,access_hash=2,file_reference=b'fixture',date=datetime.now(timezone.utc),mime_type='video/mp4',size=len(data),dc_id=1,attributes=[])


@pytest.mark.parametrize('offset',[0,PART_SIZE+37])
@pytest.mark.parametrize('parts,connections',[(3,3),(4,4),(8,8),(16,8),(16,16)])
def test_real_telethon_iterators_share_bounded_sockets_and_preserve_bytes(offset,parts,connections):
    data=bytes(range(251))*(10*1024*1024//251)+b'tail';client=Client(data);created=[]
    async def factory(client,dc):
        sender=Sender(dc);created.append(sender);return sender
    async def run():
        pool=DownloadConnections(client,connections,factory=factory);reader=DownloadClient(client,pool)
        async def collect():
            async with aclosing(iter_file(reader,document(data),offset,len(data),parts)) as chunks:
                return b''.join([x async for x in chunks])
        try:
            # Two file jobs share one account-wide connection budget.
            a,b=await asyncio.gather(collect(),collect())
            assert a==b==data[offset:]
            assert len(created)==connections and all(entry.users==0 for entry in pool.entries)
            assert not client.native
        finally:await pool.close()
        assert all(sender.closed for sender in created)
    asyncio.run(run())


def test_pause_releases_every_lease_and_resume_keeps_exact_prefix():
    data=b'A'*PART_SIZE+b'B'*PART_SIZE+b'C'*(10*1024*1024);client=Client(data);created=[]
    async def factory(client,dc):
        sender=Sender(dc);created.append(sender);return sender
    async def run():
        pool=DownloadConnections(client,3,factory=factory);reader=DownloadClient(client,pool);prefix=b''
        try:
            async with aclosing(iter_file(reader,document(data),0,len(data),3)) as chunks:
                async for chunk in chunks:
                    prefix+=chunk
                    if len(prefix)>=2*PART_SIZE:break
            assert all(entry.users==0 for entry in pool.entries)
            async with aclosing(iter_file(reader,document(data),len(prefix),len(data),3)) as chunks:
                actual=prefix+b''.join([x async for x in chunks])
            assert actual==data and len(created)==3
        finally:await pool.close()
    asyncio.run(run())


def test_file_migration_returns_old_sender_and_does_not_deadlock_pool():
    data=b'x'*(9*1024*1024+17);client=Client(data,migrate=True);created=[]
    async def factory(client,dc):
        sender=Sender(dc);created.append(sender);return sender
    async def run():
        pool=DownloadConnections(client,3,factory=factory);reader=DownloadClient(client,pool)
        try:
            async with aclosing(iter_file(reader,document(data),0,len(data),3)) as chunks:
                actual=b''.join([x async for x in chunks])
            assert actual==data and len(pool.entries)<=3
            assert all(entry.users==0 for entry in pool.entries)
            assert client.native==client.native_returns
        finally:await pool.close()
        assert all(sender.closed for sender in created)
    asyncio.run(asyncio.wait_for(run(),5))


def test_full_pool_uses_native_sender_for_another_dc_without_starving():
    client=Client(b'');created=[]
    async def factory(client,dc):
        sender=Sender(dc);created.append(sender);return sender
    async def run():
        pool=DownloadConnections(client,1,factory=factory);first=DownloadClient(client,pool);other=DownloadClient(client,pool)
        try:
            a=await first._borrow_exported_sender(1);b=await other._borrow_exported_sender(2)
            assert a is created[0] and b in client.native
            await other.release_all();await first.release_all()
            assert client.native==client.native_returns
        finally:await pool.close()
    asyncio.run(run())


def test_cancel_during_iterator_initialization_does_not_mask_cancellation():
    client=Client(b'x'*(9*1024*1024))
    async def run():
        entered=asyncio.Event()
        async def factory(client,dc):entered.set();await asyncio.sleep(10)
        pool=DownloadConnections(client,3,factory=factory)
        stream=DownloadClient(client,pool).iter_download(document(client.data),file_size=len(client.data))
        task=asyncio.create_task(anext(stream));await entered.wait();task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        await stream.close();await pool.close()
    asyncio.run(run())


def test_idle_sockets_are_closed_and_can_be_created_again():
    client=Client(b'');created=[]
    async def factory(client,dc):
        sender=Sender(dc);created.append(sender);return sender
    async def run():
        pool=DownloadConnections(client,3,idle_seconds=.005,factory=factory)
        first=await pool.borrow(1);await pool.release(first);await asyncio.sleep(.025)
        assert first.closed and not pool.entries
        second=await pool.borrow(1);assert second is not first
        await pool.release(second);await pool.close();assert second.closed and pool.idle_task is None
    asyncio.run(run())


def test_excessive_connection_count_is_capped_across_all_leases():
    from app.download_connections import MAX_FILE_CONNECTIONS
    client=Client(b'');created=[]
    async def factory(client,dc):
        sender=Sender(dc);created.append(sender);return sender
    async def run():
        pool=DownloadConnections(client,10_000,factory=factory)
        leases=await asyncio.gather(*(pool.borrow(1) for _ in range(32)))
        assert len(created)==MAX_FILE_CONNECTIONS and sum(e.users for e in pool.entries)==32
        for sender in leases:await pool.release(sender)
        assert all(e.users==0 for e in pool.entries)
        await pool.close();assert all(sender.closed for sender in created)
    asyncio.run(run())


def test_new_sender_cancellation_disconnects_socket_and_keeps_main_init(monkeypatch):
    import app.download_connections as module
    async def run():
        entered=asyncio.Event()
        class Connecting(Sender):
            async def connect(self,connection):entered.set();await asyncio.sleep(10)
        sender=Connecting(1);monkeypatch.setattr(module,'MTProtoSender',lambda *a,**kw:sender)
        class Base:
            _log={};_proxy=None;_local_addr=None;_init_request=SimpleNamespace(query='original')
            _connection=staticmethod(lambda *a,**kw:object())
            async def _get_dc(self,dc):return SimpleNamespace(ip_address='127.0.0.1',port=443,id=dc)
        base=Base();task=asyncio.create_task(create_sender(base,1));await entered.wait();task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert sender.closed and base._init_request.query=='original'
    asyncio.run(run())


def test_sender_import_uses_fresh_key_and_copy_of_main_init(monkeypatch):
    import app.download_connections as module
    async def run():
        class Imported(Sender):
            async def connect(self,connection):pass
            async def send(self,request):
                assert request.query is not base._init_request
                assert request.query.query.id==123 and base._init_request.query=='original'
        sender=Imported(1)
        def construct(key,**kwargs):assert key is None;return sender
        monkeypatch.setattr(module,'MTProtoSender',construct)
        class Base:
            _log={};_proxy=None;_local_addr=None;_init_request=SimpleNamespace(query='original')
            _connection=staticmethod(lambda *a,**kw:object())
            async def _get_dc(self,dc):return SimpleNamespace(ip_address='127.0.0.1',port=443,id=dc)
            async def __call__(self,request):return SimpleNamespace(id=123,bytes=b'fixture-export')
        base=Base();assert await create_sender(base,1) is sender
        assert base._init_request.query=='original';await sender.disconnect()
    asyncio.run(run())


def test_existing_file_authorization_opens_fresh_sessions_without_export(monkeypatch):
    import app.download_connections as module
    from telethon import functions
    async def run():
        key=bytes(range(256));states=[]
        from telethon.network.mtprotosender import MTProtoSender
        class Reused(Sender):
            async def connect(self,connection):pass
            async def send(self,request):
                assert isinstance(request.query.query,functions.help.GetConfigRequest)
        def construct(auth_key,**kwargs):
            assert bytes(auth_key.key)==key
            native=MTProtoSender(auth_key,loggers=defaultdict(lambda:logging.getLogger('test')))
            states.append(native._state.id)
            return Reused(1)
        monkeypatch.setattr(module,'MTProtoSender',construct)
        class Base:
            _log={};_proxy=None;_local_addr=None;_init_request=SimpleNamespace(query='original')
            _connection=staticmethod(lambda *a,**kw:object())
            async def _get_dc(self,dc):return SimpleNamespace(ip_address='127.0.0.1',port=443,id=dc)
            async def __call__(self,request):raise AssertionError('File key must not export again')
        base=Base()
        for _ in range(3):
            sender=await create_sender(base,1,auth_key=key);await sender.disconnect()
        assert len(set(states))==3 and base._init_request.query=='original'
    asyncio.run(run())
