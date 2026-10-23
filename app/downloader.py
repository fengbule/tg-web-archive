import asyncio, json, logging, mimetypes, os, shutil, subprocess, time
from pathlib import Path
from .db import now
from contextlib import aclosing
from .parallel_download import iter_file, MAX_PARALLEL_READS
from .download_connections import DownloadConnections, DownloadClient, MAX_FILE_CONNECTIONS
from telethon.errors import FloodWaitError, FloodPremiumWaitError

log=logging.getLogger('tvm.downloader')
class UserCancelled(Exception): pass
class DownloadPaused(Exception): pass
class Downloader:
    def __init__(self,db,tg,root:Path,concurrency=2,min_free_gb=10):
        self.db=db; self.tg=tg; self.root=root; self.media=root/'media'; self.temp=root/'temp'; self.thumbs=root/'thumbnails'
        self.concurrency=concurrency; self.reserve=int(min_free_gb*1024**3); self.workers=[]; self.cancelled=set(); self.pause_requested=set(); self.stopping=False
        self.transcoder=None
        self.parts=max(1,min(MAX_PARALLEL_READS,int(os.getenv('DOWNLOAD_PARTS','8'))))
        self.connections=max(1,min(MAX_FILE_CONNECTIONS,int(os.getenv('DOWNLOAD_CONNECTIONS','8'))))
        self.pools={}
    async def start(self): self.workers=[asyncio.create_task(self.worker(i)) for i in range(self.concurrency)]
    async def stop(self):
        self.stopping=True
        for w in self.workers: w.cancel()
        await asyncio.gather(*self.workers,return_exceptions=True)
        await asyncio.gather(*(pool.close() for pool in self.pools.values()),return_exceptions=True)
        self.pools.clear()
    def enqueue(self,item):
        t=now(); safe=Path(item['file_name']).name.replace('\x00','')[:240] or f"video_{item['message_id']}.mp4"; account_id=int(item.get('account_id') or self.tg.active_id)
        try:
            cur=self.db.execute('''INSERT INTO downloads(account_id,channel_id,message_id,channel_title,file_name,total_bytes,status,created_at,updated_at)
              VALUES(?,?,?,?,?,?,'queued',?,?)''',(account_id,int(item['channel_id']),int(item['message_id']),item.get('channel_title',''),safe,int(item.get('size',0)),t,t)); return cur.lastrowid,False
        except Exception:
            old=self.db.one('SELECT id,status FROM downloads WHERE account_id=? AND channel_id=? AND message_id=?',(account_id,int(item['channel_id']),int(item['message_id'])))
            if not old: raise
            return old['id'],True
    async def worker(self,index):
        log.info('下载 worker 已启动 index=%s',index)
        while not self.stopping:
            job=None
            try:
                job=self.ready_job()
                if not job: await asyncio.sleep(1); continue
                changed=self.db.execute("UPDATE downloads SET status='downloading',error='',updated_at=? WHERE id=? AND status='queued'",(now(),job['id'])).rowcount
                if not changed: await asyncio.sleep(.1); continue
                await self.download(job)
            except asyncio.CancelledError: raise
            except (FloodWaitError,FloodPremiumWaitError) as e:
                if job:self.defer_for_rate_limit(job,int(e.seconds))
                await asyncio.sleep(1)
            except Exception as e:
                log.exception('下载 worker 异常 index=%s id=%s',index,job['id'] if job else '-')
                if job:
                    retry=int(job.get('retry_count') or 0)+1
                    try:
                        if self.retryable(e) and retry<=3:
                            self.db.execute("UPDATE downloads SET status='retrying',retry_count=?,error=?,speed=0,updated_at=? WHERE id=?",(retry,f'网络中断，等待自动续传（{retry}/3）',now(),job['id']))
                            await asyncio.sleep(5*retry)
                            self.db.execute("UPDATE downloads SET status='queued',updated_at=? WHERE id=? AND status='retrying'",(now(),job['id']))
                        else:
                            self.db.execute("UPDATE downloads SET status='failed',error=?,speed=0,updated_at=? WHERE id=?",(self.friendly(e),now(),job['id']))
                    except Exception: log.exception('下载任务失败状态写入失败 id=%s',job['id'])
                await asyncio.sleep(1)
    def ready_job(self):
        return self.db.one("""SELECT * FROM downloads AS d WHERE status='queued'
          AND NOT EXISTS (SELECT 1 FROM config WHERE key='download_wait_until:' || d.account_id
                          AND CAST(value AS REAL)>?) ORDER BY id LIMIT 1""",(time.time(),))
    def defer_for_rate_limit(self,job,seconds):
        account_id=int(job.get('account_id') or 1);key=f'download_wait_until:{account_id}'
        deadline=time.time()+max(1,seconds)+1
        old=self.db.one('SELECT value FROM config WHERE key=?',(key,))
        if old:deadline=max(deadline,float(old['value']))
        self.db.execute('INSERT OR REPLACE INTO config(key,value) VALUES(?,?)',(key,str(deadline)))
        temp=self.temp/f"{job['id']}.part";current=temp.stat().st_size if temp.exists() else int(job.get('downloaded_bytes') or 0)
        paused=job['id'] in self.pause_requested
        self.pause_requested.discard(job['id'])
        if job['id'] in self.cancelled:
            temp.unlink(missing_ok=True);self.cancelled.discard(job['id'])
            self.db.execute("UPDATE downloads SET status='cancelled',downloaded_bytes=0,temp_path='',speed=0,error='',updated_at=? WHERE id=?",(now(),job['id']))
            return
        self.db.execute("UPDATE downloads SET status=?,downloaded_bytes=?,speed=0,error=?,updated_at=? WHERE id=?",
          ('paused' if paused else 'queued',current,f'Telegram 要求等待 {max(1,seconds)} 秒，将自动续传',now(),job['id']))
        log.warning('Telegram 下载等待 account=%s seconds=%s；保留断点与重试次数',account_id,seconds)
    def retryable(self,e):
        s=str(e)
        return not isinstance(e,(UserCancelled,ValueError)) and not any(x in s for x in ('磁盘','原消息不存在','不可访问'))
    def friendly(self,e):
        s=str(e)
        if '空间' in s: return s
        if isinstance(e,(ConnectionError,TimeoutError,OSError)) or any(x in type(e).__name__.lower() for x in ('timeout','connection','rpc')): return 'Telegram 网络连接中断，可点击重试继续下载'
        return '下载失败，可点击重试继续下载'
    async def download(self,job):
        temp=self.temp/f"{job['id']}.part"
        existing=temp.stat().st_size if temp.exists() else 0
        free=shutil.disk_usage(self.root).free
        if free-self.reserve < max(job['total_bytes']-existing,0):
            self.db.execute("UPDATE downloads SET status='paused',error='磁盘剩余空间不足，任务已暂停',updated_at=? WHERE id=?",(now(),job['id'])); return
        c=await self.tg.get_client(job.get('account_id',1)); entity=await c.get_entity(job['channel_id']); msg=await c.get_messages(entity,ids=job['message_id'])
        if not msg or not msg.video: raise RuntimeError('Telegram 原消息不存在或已不可访问')
        channel_dir=self.media/str(job.get('account_id',1))/str(job['channel_id']); channel_dir.mkdir(parents=True,exist_ok=True)
        final=channel_dir/f"{job['message_id']}_{job['file_name']}"; temp=self.temp/f"{job['id']}.part"; total=int(getattr(msg.video,'size',0) or job['total_bytes'] or 0)
        existing=temp.stat().st_size if temp.exists() else 0
        if total and existing>total: temp.unlink(missing_ok=True); existing=0
        if shutil.disk_usage(self.root).free-self.reserve < max(total-existing,0):
            self.db.execute("UPDATE downloads SET status='paused',speed=0,error='磁盘剩余空间不足，任务已暂停',updated_at=? WHERE id=?",(now(),job['id'])); return
        started=time.monotonic(); last_t=started; last_b=existing
        async def progress(cur,total):
            nonlocal last_t,last_b
            if job['id'] in self.cancelled: raise UserCancelled()
            if job['id'] in self.pause_requested: raise DownloadPaused()
            t=time.monotonic()
            if t-last_t>=0.7 or cur==total:
                if shutil.disk_usage(self.root).free < self.reserve:
                    raise RuntimeError('磁盘已达到安全保护线，下载已停止')
                speed=(cur-last_b)/max(t-last_t,.01); self.db.execute('UPDATE downloads SET downloaded_bytes=?,total_bytes=?,speed=?,updated_at=? WHERE id=?',(cur,total,speed,now(),job['id'])); last_t=t; last_b=cur
        self.db.execute('UPDATE downloads SET temp_path=?,downloaded_bytes=?,total_bytes=?,updated_at=? WHERE id=?',(str(temp),existing,total,now(),job['id']))
        try:
            reader=c
            if self.connections>1 and self.parts>1 and total-existing>=8*1024*1024 and hasattr(c,'_borrow_exported_sender'):
                pool=self.pools.get(c)
                if pool is None or pool.closed:
                    pool=self.pools[c]=DownloadConnections(c,self.connections)
                    c._archive_file_pool=pool
                reader=DownloadClient(c,pool)
            with temp.open('ab' if existing else 'wb') as f:
                current=existing
                if job['id'] in self.cancelled: raise UserCancelled()
                if job['id'] in self.pause_requested: raise DownloadPaused()
                async with aclosing(iter_file(reader,msg.video,existing,total,self.parts)) as chunks:
                    async for chunk in chunks:
                        if job['id'] in self.cancelled: raise UserCancelled()
                        if job['id'] in self.pause_requested: raise DownloadPaused()
                        f.write(chunk); current+=len(chunk); await progress(current,total)
                if job['id'] in self.cancelled: raise UserCancelled()
                if job['id'] in self.pause_requested: raise DownloadPaused()
                f.flush(); os.fsync(f.fileno())
            if not temp.exists(): raise RuntimeError('未生成下载文件')
            if total and temp.stat().st_size!=total:
                raise ConnectionError('下载文件大小不完整，保留临时文件等待续传')
            # Probe the partial file before publishing it. Pause, cancellation or
            # shutdown during ffprobe must still leave the job recoverable.
            meta=await asyncio.to_thread(self.probe,temp,job['id'])
            with self.db.lock:
                if job['id'] in self.cancelled: raise UserCancelled()
                if job['id'] in self.pause_requested: raise DownloadPaused()
                os.replace(temp,final)
                self.db.execute('''INSERT OR REPLACE INTO media(download_id,account_id,channel_id,message_id,channel_title,file_name,file_path,thumb_path,size,duration,width,height,mime,caption,message_date,downloaded_at)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(job['id'],job.get('account_id',1),job['channel_id'],job['message_id'],job['channel_title'],job['file_name'],str(final),meta['thumb'],final.stat().st_size,meta['duration'],meta['width'],meta['height'],mimetypes.guess_type(final.name)[0] or 'application/octet-stream',msg.message or '',msg.date.isoformat(),now()))
                self.db.execute("UPDATE downloads SET status='completed',downloaded_bytes=?,total_bytes=?,speed=0,error='',temp_path='',updated_at=? WHERE id=?",(final.stat().st_size,final.stat().st_size,now(),job['id']))
                row=self.db.one('SELECT id FROM media WHERE account_id=? AND channel_id=? AND message_id=?',(job.get('account_id',1),job['channel_id'],job['message_id']))
                if row and self.transcoder:
                    self.transcoder.enqueue_faststart(int(row['id']))
                    if self.transcoder.auto_smooth: self.transcoder.enqueue_smooth(int(row['id']))
        except UserCancelled:
            temp.unlink(missing_ok=True); (self.thumbs/f"{job['id']}.jpg").unlink(missing_ok=True); self.cancelled.discard(job['id']); self.db.execute("UPDATE downloads SET status='cancelled',downloaded_bytes=0,temp_path='',speed=0,error='',updated_at=? WHERE id=?",(now(),job['id'])); return
        except DownloadPaused:
            current=temp.stat().st_size if temp.exists() else existing
            self.pause_requested.discard(job['id'])
            self.db.execute("UPDATE downloads SET status='paused',downloaded_bytes=?,speed=0,error='已暂停，临时文件已保留',updated_at=? WHERE id=?",(current,now(),job['id'])); return
        except asyncio.CancelledError:
            current=temp.stat().st_size if temp.exists() else existing
            self.db.execute("UPDATE downloads SET status='queued',downloaded_bytes=?,speed=0,error='服务重启，稍后自动续传',updated_at=? WHERE id=?",(current,now(),job['id'])); return
    def probe(self,path,job_id):
        d={'duration':0,'width':0,'height':0,'thumb':''}
        try:
            p=subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=width,height:format=duration','-of','json',str(path)],capture_output=True,text=True,timeout=30,check=True)
            x=json.loads(p.stdout); st=(x.get('streams') or [{}])[0]; d.update(duration=float(x.get('format',{}).get('duration') or 0),width=int(st.get('width') or 0),height=int(st.get('height') or 0))
            thumb=self.thumbs/f'{job_id}.jpg'; subprocess.run(['ffmpeg','-y','-ss','1','-i',str(path),'-frames:v','1','-vf','scale=480:-2',str(thumb)],capture_output=True,timeout=60); 
            if thumb.exists(): d['thumb']=str(thumb)
        except Exception: log.warning('媒体信息读取失败 id=%s',job_id)
        return d
    def cancel(self,id):
        with self.db.lock:
            row=self.db.one('SELECT status FROM downloads WHERE id=?',(id,))
            if not row or row['status'] not in ('queued','retrying','paused','failed','downloading','pausing'):
                return False
            self.pause_requested.discard(id)
            if row['status'] in ('downloading','pausing'):
                self.cancelled.add(id)
            else:
                (self.temp/f'{id}.part').unlink(missing_ok=True)
                self.db.execute("UPDATE downloads SET status='cancelled',downloaded_bytes=0,temp_path='',speed=0,error='',updated_at=? WHERE id=?",(now(),id))
                self.cancelled.discard(id)
            return True
    def pause(self,id):
        with self.db.lock:
            row=self.db.one('SELECT status FROM downloads WHERE id=?',(id,))
            if not row: return False
            if row['status']=='downloading':
                self.pause_requested.add(id)
                self.db.execute("UPDATE downloads SET status='pausing',error='正在安全暂停…',updated_at=? WHERE id=?",(now(),id)); return True
            changed=self.db.execute("UPDATE downloads SET status='paused',speed=0,error='已暂停，临时文件已保留',updated_at=? WHERE id=? AND status IN ('queued','retrying')",(now(),id)).rowcount
            return bool(changed)
    def resume(self,id):
        return self._requeue(id,('paused',))
    def retry(self,id):
        return self._requeue(id,('failed','cancelled','paused','retrying'))
    def _requeue(self,id,statuses):
        with self.db.lock:
            changed=self.db.execute("UPDATE downloads SET status='queued',speed=0,error='',retry_count=0,updated_at=? WHERE id=? AND status IN ("+','.join('?' for _ in statuses)+')',(now(),id,*statuses)).rowcount
            if changed:
                self.pause_requested.discard(id); self.cancelled.discard(id)
            return bool(changed)
