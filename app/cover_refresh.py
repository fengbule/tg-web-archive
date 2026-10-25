"""One bounded background refresh; never re-downloads or modifies video files."""
import asyncio,time
from .telegram_service import TelegramAccountService


class CoverRefresh:
    def __init__(self,db,tg):
        self.db=db;self.tg=tg;self.task=None
        self.state=self._state('idle',0)

    @staticmethod
    def _state(status,total):
        return {'status':status,'total':total,'done':0,'original':0,'updated':0,'retained':0,'fallback':0,'unavailable':0}

    def start(self):
        if self.task and not self.task.done():return dict(self.state)
        rows=self.db.all('SELECT account_id,channel_id,message_id FROM media ORDER BY id')
        self.state=self._state('running',len(rows))
        self.task=asyncio.create_task(self._run(rows))
        return dict(self.state)

    async def _run(self,rows):
        try:
            for row in rows:
                try:
                    started=time.time_ns()
                    path=await self.tg.service(row['account_id']).thumbnail(row['channel_id'],row['message_id'],refresh=True)
                    key='unavailable' if not path else 'fallback' if TelegramAccountService.thumbnail_origin(path)=='local-frame' else 'original'
                    if key=='original':self.state['updated' if path.stat().st_mtime_ns>=started else 'retained']+=1
                except asyncio.CancelledError:raise
                except Exception:key='unavailable'
                self.state[key]+=1;self.state['done']+=1
                await asyncio.sleep(.2)
            self.state['status']='completed'
        except asyncio.CancelledError:
            self.state['status']='interrupted'
            raise

    async def stop(self):
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task,return_exceptions=True)
