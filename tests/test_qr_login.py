import asyncio
import base64
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from telethon.errors import SessionPasswordNeededError
from app.qr_login import QRLoginFlow


class FakeQR:
    def __init__(self):
        self.expires = datetime.now(timezone.utc) + timedelta(seconds=30)
        self.url = 'tg://login?token=test-only-token'
        self.result = asyncio.Queue()
        self.refreshes = 0
        self.waiting = False

    async def wait(self, timeout=None):
        self.waiting = True
        try:
            value = await asyncio.wait_for(self.result.get(), timeout)
            if isinstance(value, Exception):
                raise value
            return value
        finally:
            self.waiting = False

    async def recreate(self):
        self.refreshes += 1
        self.url = 'tg://login?token=test-only-refreshed'
        self.expires = datetime.now(timezone.utc) + timedelta(seconds=30)


class FakeClient:
    def __init__(self, qr): self.qr = qr
    async def is_user_authorized(self): return False
    async def qr_login(self): return self.qr


async def settle():
    for _ in range(12): await asyncio.sleep(0)


def test_qr_success_registers_waiter_and_clears_image():
    async def check():
        qr=FakeQR(); flow=QRLoginFlow()
        state=await flow.start(FakeClient(qr))
        assert qr.waiting and state['state']=='waiting'
        assert base64.b64decode(state['image'].split(',')[1]).startswith(b'\x89PNG')
        await qr.result.put(SimpleNamespace(id=123))
        await settle()
        assert flow.snapshot()=={'state':'authorized'}
        await flow.cancel()
    asyncio.run(check())


def test_qr_expiration_refreshes_image_and_cancel_stops_waiter():
    async def check():
        qr=FakeQR(); flow=QRLoginFlow()
        before=await flow.start(FakeClient(qr))
        await qr.result.put(asyncio.TimeoutError())
        await settle()
        assert qr.refreshes==1 and flow.snapshot()['image']!=before['image']
        task=flow.task
        await flow.cancel()
        assert task.cancelled() and not qr.waiting and flow.snapshot()=={'state':'idle'}
    asyncio.run(check())


def test_qr_two_factor_branch_clears_token():
    async def check():
        qr=FakeQR(); flow=QRLoginFlow(); await flow.start(FakeClient(qr))
        await qr.result.put(SessionPasswordNeededError(request=None)); await settle()
        assert flow.snapshot()=={'state':'password_needed'}
        await flow.cancel()
    asyncio.run(check())


def test_qr_upstream_error_does_not_expose_token():
    async def check():
        qr=FakeQR(); flow=QRLoginFlow(); await flow.start(FakeClient(qr))
        await qr.result.put(RuntimeError('secret-token-value')); await settle()
        assert flow.snapshot()['state']=='error'
        assert 'secret-token' not in str(flow.snapshot()) and 'image' not in flow.snapshot()
        await flow.cancel()
    asyncio.run(check())


def test_qr_total_wait_is_bounded():
    async def check():
        qr=FakeQR(); flow=QRLoginFlow(max_duration=0.01)
        await flow.start(FakeClient(qr)); await asyncio.sleep(0.04)
        assert flow.snapshot()=={'state':'expired'} and not qr.waiting
        await flow.cancel()
    asyncio.run(check())


def test_new_qr_request_cancels_previous_waiter():
    async def check():
        old,new=FakeQR(),FakeQR(); flow=QRLoginFlow()
        await flow.start(FakeClient(old)); task=flow.task
        await flow.start(FakeClient(new))
        assert task.cancelled() and not old.waiting and new.waiting
        await flow.cancel()
    asyncio.run(check())
