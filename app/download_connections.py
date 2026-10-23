"""Bounded cross-DC file connections for the account's existing Telethon client.

Telethon 1.x shares one exported sender per DC. More iterators on that sender
cannot overcome a slow individual connection. This facade gives native download
iterators a small reusable pool; the login Session is never cloned or exported.
"""
import asyncio
import copy
import logging
import os
import time
from dataclasses import dataclass
from telethon import functions
from telethon.client.downloads import DownloadMethods
from telethon.network.mtprotosender import MTProtoSender
from telethon.crypto import AuthKey
from telethon.errors import AuthKeyNotFound, AuthKeyUnregisteredError
from telethon.network.connection import ConnectionTcpAbridged, ConnectionTcpObfuscated
from telethon.tl.alltlobjects import LAYER

MAX_FILE_CONNECTIONS = 16
log = logging.getLogger('tvm.file_connections')


async def create_sender(client, dc_id, *, auth_key=None):
    dc = await client._get_dc(dc_id)
    sender = MTProtoSender(AuthKey(auth_key) if auth_key else None, loggers=client._log)
    try:
        async with asyncio.timeout(25):
            await sender.connect(client._connection(dc.ip_address, dc.port, dc.id,
                loggers=client._log, proxy=client._proxy, local_addr=client._local_addr))
            # Do not mutate the main client's init request while other requests
            # are in flight. Each socket has independent MTProto session state.
            init = copy.copy(client._init_request)
            if auth_key:
                # Each sender has a fresh MTProto session ID. Reuse only the
                # pool's in-memory file authorization for this DC, never the
                # main login Session/key or keys from another host.
                init.query = functions.help.GetConfigRequest()
            else:
                auth = await client(functions.auth.ExportAuthorizationRequest(dc_id))
                init.query = functions.auth.ImportAuthorizationRequest(id=auth.id, bytes=auth.bytes)
            await sender.send(functions.InvokeWithLayerRequest(LAYER, init))
        log.info('文件连接已建立 dc=%s address=%s transport=%s reused_file_key=%s',
                 dc_id, dc.ip_address, client._connection.__name__, bool(auth_key))
        return sender
    except BaseException:
        await sender.disconnect()
        raise


class ConnectionSettings:
    """File-only settings; the account's main connection and Session stay intact."""
    def __init__(self, base, endpoint, transport):
        self.base = base
        self.endpoint = endpoint
        self._connection = transport

    def __getattr__(self, name):
        return getattr(self.base, name)

    async def __call__(self, *args, **kwargs):
        return await self.base(*args, **kwargs)

    async def _get_dc(self, dc_id):
        if dc_id == self.endpoint.id:
            return self.endpoint
        return await self.base._get_dc(dc_id)


class FileConnectionFactory:
    """Opt-in route preference from Telegram's config, with native fallback."""
    def __init__(self, client, transport=None, strategy=None):
        self.client = client
        self.transport = transport or os.getenv('DOWNLOAD_TRANSPORT', 'native')
        self.strategy = strategy or os.getenv('DOWNLOAD_DC_STRATEGY', 'primary')
        if self.transport not in ('native', 'abridged', 'obfuscated'):
            self.transport = 'native'
        if self.strategy not in ('primary', 'alternate'):
            self.strategy = 'primary'
        self.config = None
        self.retry_after = 0
        self.auth_keys = {}

    async def _create(self, client, dc_id):
        try:
            sender = await create_sender(client, dc_id, auth_key=self.auth_keys.get(dc_id))
        except (AuthKeyNotFound, AuthKeyUnregisteredError):
            self.auth_keys.pop(dc_id, None)
            raise
        auth = getattr(sender, 'auth_key', None)
        if auth and auth.key:
            self.auth_keys[dc_id] = bytes(auth.key)
        return sender

    def clear_auth(self):
        self.auth_keys.clear()
        self.config = None

    async def __call__(self, client, dc_id):
        if (self.transport == 'native' and self.strategy == 'primary') or time.monotonic() < self.retry_after:
            return await self._create(client, dc_id)
        try:
            primary = await client._get_dc(dc_id)
            endpoint = primary
            if self.strategy == 'alternate':
                if self.config is None:
                    self.config = await client(functions.help.GetConfigRequest())
                # Never guess an address or move authorizations between DCs.
                # Match native address family and role; absence is harmless.
                endpoint = next((option for option in self.config.dc_options
                    if option.id == dc_id and not option.cdn
                    and bool(option.ipv6) == bool(primary.ipv6)
                    and bool(option.media_only) == bool(primary.media_only)
                    and option.ip_address != primary.ip_address), primary)
            transport = {'abridged': ConnectionTcpAbridged,
                         'obfuscated': ConnectionTcpObfuscated}.get(self.transport, client._connection)
            return await self._create(ConnectionSettings(client, endpoint, transport), dc_id)
        except (TimeoutError, ConnectionError, OSError) as error:
            # Rate-limit/RPC errors and cancellation propagate unchanged. Only
            # network setup failures may switch back to the original route.
            self.config = None
            self.retry_after = time.monotonic() + 60
            log.warning('文件连接初始化失败，临时回退原始线路 (%s)', type(error).__name__)
            return await self._create(client, dc_id)


@dataclass
class Entry:
    sender: object
    dc_id: int
    users: int = 0


class DownloadConnections:
    """At most N file sockets per account, shared across jobs and destination DCs."""
    def __init__(self, client, limit=3, idle_seconds=30, factory=None):
        self.client = client
        self.limit = max(1, min(MAX_FILE_CONNECTIONS, int(limit)))
        self.idle_seconds = idle_seconds
        self.factory = factory or FileConnectionFactory(client)
        self.entries = []
        self.condition = asyncio.Condition()
        self.idle_task = None
        self.closed = False

    async def borrow(self, dc_id):
        async with self.condition:
            while True:
                if self.closed:
                    raise ConnectionError('文件连接池已关闭，请稍后续传')
                matching = [entry for entry in self.entries if entry.dc_id == dc_id]
                # Prefer allocating unused capacity to increase TCP throughput;
                # once full, requests to the same DC share the least busy slot.
                if len(self.entries) < self.limit:
                    sender = await self.factory(self.client, dc_id)
                    entry = Entry(sender, dc_id, 1)
                    self.entries.append(entry)
                    return sender
                if matching:
                    entry = min(matching, key=lambda entry: entry.users)
                    entry.users += 1
                    return entry.sender
                idle = next((entry for entry in self.entries if not entry.users), None)
                if idle:
                    self.entries.remove(idle)
                    await idle.sender.disconnect()
                    continue
                # A second job can target another DC while every pool slot is
                # occupied. Let it use Telethon's shared sender, rather than
                # wait for a potentially multi-hour file to finish.
                return None

    async def release(self, sender):
        async with self.condition:
            entry = next((entry for entry in self.entries if entry.sender is sender), None)
            if entry:
                entry.users = max(0, entry.users - 1)
                self.condition.notify_all()
                if not any(entry.users for entry in self.entries) and self.idle_task is None:
                    self.idle_task = asyncio.create_task(self._expire_idle())

    async def _expire_idle(self):
        try:
            await asyncio.sleep(self.idle_seconds)
            async with self.condition:
                idle = [entry for entry in self.entries if not entry.users]
                self.entries = [entry for entry in self.entries if entry.users]
                for entry in idle:
                    await entry.sender.disconnect()
                self.condition.notify_all()
        finally:
            self.idle_task = None

    async def close(self):
        async with self.condition:
            self.closed = True
            self.condition.notify_all()
            task = self.idle_task
            self.idle_task = None
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        async with self.condition:
            entries, self.entries = self.entries, []
            for entry in entries:
                await entry.sender.disconnect()
            clear = getattr(self.factory, 'clear_auth', None)
            if clear:
                clear()


class DownloadClient:
    """Native Telethon iteration and error handling, with explicit sender ownership."""
    def __init__(self, client, pool):
        self.base = client
        self.pool = pool
        self.leases = []

    def __getattr__(self, name):
        return getattr(self.base, name)

    async def __call__(self, *args, **kwargs):
        return await self.base(*args, **kwargs)

    def iter_download(self, file, **kwargs):
        scope = DownloadClient(self.base, self.pool)
        iterator = DownloadMethods._iter_download(scope, file, **kwargs)
        # Native close() also needs to be safe if cancellation happens during
        # _init(), before the exported sender has been assigned.
        iterator._sender = None
        return DownloadIterator(iterator, scope)

    async def _borrow_exported_sender(self, dc_id):
        # FileMigrateError replaces the sender inside a native iterator. Release
        # its former lease before allocating the new DC to avoid orphaned slots.
        await self.release_all()
        sender = await self.pool.borrow(dc_id) if dc_id != self.base.session.dc_id else None
        pooled = sender is not None
        if not pooled:
            sender = await self.base._borrow_exported_sender(dc_id)
        self.leases.append((sender, pooled))
        return sender

    async def _return_exported_sender(self, sender):
        index = next((i for i, pair in enumerate(self.leases) if pair[0] is sender), None)
        if index is not None:
            _, pooled = self.leases.pop(index)
            if pooled:
                await self.pool.release(sender)
            else:
                await self.base._return_exported_sender(sender)

    async def release_all(self):
        for sender, _ in list(self.leases):
            await self._return_exported_sender(sender)


class DownloadIterator:
    def __init__(self, iterator, scope):
        self.iterator = iterator
        self.scope = scope

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await anext(self.iterator)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def close(self):
        try:
            await self.iterator.close()
        finally:
            await self.scope.release_all()
