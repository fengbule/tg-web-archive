"""Short-lived, in-memory QR login state. Tokens never enter logs or SQLite."""
import asyncio
import base64
from datetime import datetime, timezone
from io import BytesIO
import time

import qrcode
from telethon.errors import SessionPasswordNeededError


class QRLoginFlow:
    def __init__(self, max_duration=300):
        self.task = None
        self.state = {'state': 'idle'}
        self.lock = asyncio.Lock()
        self.max_duration = max_duration

    def snapshot(self):
        return dict(self.state)

    def _display(self, qr):
        image = BytesIO()
        qrcode.make(qr.url, box_size=6, border=4).save(image, format='PNG')
        self.state = {'state': 'waiting', 'expires_at': qr.expires.isoformat(),
                      'image': 'data:image/png;base64,' + base64.b64encode(image.getvalue()).decode()}

    async def _stop(self):
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        self.task = None
        self.state = {'state': 'idle'}

    async def cancel(self):
        async with self.lock:
            await self._stop()

    async def start(self, client):
        async with self.lock:
            await self._stop()
            if await client.is_user_authorized():
                self.state = {'state': 'authorized'}
            else:
                qr = await client.qr_login()
                self._display(qr)
                self.task = asyncio.create_task(self._watch(qr))
                # Register Telethon's login-token listener before returning the image.
                await asyncio.sleep(0)
            return self.snapshot()

    async def _watch(self, qr):
        deadline = time.monotonic() + self.max_duration
        try:
            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                ttl = max(0.1, (qr.expires - datetime.now(timezone.utc)).total_seconds())
                try:
                    await qr.wait(timeout=min(ttl, remaining))
                    self.state = {'state': 'authorized'}
                    return
                except asyncio.TimeoutError:
                    if time.monotonic() >= deadline:
                        break
                    await qr.recreate()
                    self._display(qr)
            self.state = {'state': 'expired'}
        except SessionPasswordNeededError:
            self.state = {'state': 'password_needed'}
        except asyncio.CancelledError:
            raise
        except Exception:
            # Upstream exceptions may include auth tokens: expose only a fixed message.
            self.state = {'state': 'error', 'message': '扫码登录暂时失败，请重新生成二维码。'}
