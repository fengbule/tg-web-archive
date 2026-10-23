import asyncio
from types import SimpleNamespace

import pytest
from telethon.errors import FloodWaitError
from telethon.network.connection import ConnectionTcpAbridged
from app.download_connections import FileConnectionFactory


def endpoint(ip='192.0.2.1',dc=1,**kwargs):
    values=dict(id=dc,ip_address=ip,port=443,ipv6=False,cdn=False,media_only=False)
    values.update(kwargs);return SimpleNamespace(**values)


class Client:
    _connection=object
    def __init__(self,options=None):
        self.primary=endpoint();self.options=options or [self.primary];self.queries=0
        self.session=SimpleNamespace(dc_id=5,server_address='192.0.2.50')
    async def _get_dc(self,dc):return self.primary
    async def __call__(self,request):
        self.queries+=1;return SimpleNamespace(dc_options=self.options)


def test_default_factory_keeps_native_settings_and_avoids_extra_config(monkeypatch):
    import app.download_connections as module
    client=Client();calls=[]
    async def create(base,dc,**kwargs):calls.append((base,dc));return 'sender'
    monkeypatch.setattr(module,'create_sender',create)
    assert asyncio.run(FileConnectionFactory(client,'native','primary')(client,1))=='sender'
    assert calls==[(client,1)] and client.queries==0


def test_alternate_uses_only_configured_same_dc_role_family_and_caches_config(monkeypatch):
    import app.download_connections as module
    primary=endpoint();valid=endpoint('192.0.2.2')
    client=Client([primary,endpoint('192.0.2.3',dc=2),endpoint('192.0.2.4',cdn=True),endpoint('::1',ipv6=True),endpoint('192.0.2.5',media_only=True),valid])
    calls=[]
    async def create(settings,dc,**kwargs):
        calls.append(settings)
        assert (await settings._get_dc(dc)) is valid
        assert settings._connection is ConnectionTcpAbridged
        assert settings.session is client.session
        return 'sender'
    monkeypatch.setattr(module,'create_sender',create)
    async def run():
        factory=FileConnectionFactory(client,'abridged','alternate')
        await factory(client,1);await factory(client,1)
    asyncio.run(run())
    assert client.queries==1 and len(calls)==2
    assert client._connection is object and client.session.server_address=='192.0.2.50'


def test_missing_alternate_stays_on_native_endpoint(monkeypatch):
    import app.download_connections as module
    client=Client()
    async def create(settings,dc,**kwargs):
        assert (await settings._get_dc(dc)) is client.primary
        return 'sender'
    monkeypatch.setattr(module,'create_sender',create)
    assert asyncio.run(FileConnectionFactory(client,'abridged','alternate')(client,1))=='sender'


def test_network_setup_failure_falls_back_and_cools_down_preferred_route(monkeypatch):
    import app.download_connections as module
    client=Client([endpoint(),endpoint('192.0.2.2')]);calls=[]
    async def create(settings,dc,**kwargs):
        calls.append(settings)
        if settings is not client:raise TimeoutError()
        return 'native sender'
    monkeypatch.setattr(module,'create_sender',create)
    async def run():
        factory=FileConnectionFactory(client,'abridged','alternate')
        assert await factory(client,1)=='native sender'
        assert await factory(client,1)=='native sender'
        assert factory.retry_after>0 and factory.config is None
    asyncio.run(run())
    assert len(calls)==3 and calls[1:] == [client,client]


@pytest.mark.parametrize('error',[FloodWaitError(None,capture=5),asyncio.CancelledError()])
def test_rpc_rate_wait_and_cancellation_never_trigger_route_fallback(monkeypatch,error):
    import app.download_connections as module
    client=Client([endpoint(),endpoint('192.0.2.2')]);calls=[]
    async def create(settings,dc,**kwargs):calls.append(settings);raise error
    monkeypatch.setattr(module,'create_sender',create)
    async def run():
        with pytest.raises(type(error)):
            await FileConnectionFactory(client,'abridged','alternate')(client,1)
    asyncio.run(run());assert len(calls)==1 and calls[0] is not client


def test_unknown_settings_return_to_native_without_using_an_arbitrary_address(monkeypatch):
    import app.download_connections as module
    client=Client()
    async def create(base,dc,**kwargs):assert base is client;return 'sender'
    monkeypatch.setattr(module,'create_sender',create)
    assert asyncio.run(FileConnectionFactory(client,'unsupported','https://unknown.invalid')(client,1))=='sender'
    assert client.queries==0


def test_file_key_is_reused_only_within_its_dc_and_cleared_on_close(monkeypatch):
    import app.download_connections as module
    client=Client();keys=[];senders=[]
    async def create(base,dc,*,auth_key=None):
        keys.append((dc,auth_key))
        class Sender:
            def __init__(self):self.auth_key=SimpleNamespace(key=bytes([dc])*256);self.closed=False
            async def disconnect(self):self.closed=True
        sender=Sender();senders.append(sender);return sender
    monkeypatch.setattr(module,'create_sender',create)
    async def run():
        factory=FileConnectionFactory(client,'native','primary')
        pool=module.DownloadConnections(client,8,factory=factory)
        leases=[await pool.borrow(1) for _ in range(8)]
        for sender in leases:await pool.release(sender)
        await factory(client,2)
        assert keys==[(1,None)]+[(1,b'\x01'*256)]*7+[(2,None)]
        assert set(factory.auth_keys)=={1,2}
        await pool.close();assert not factory.auth_keys
    asyncio.run(run())
