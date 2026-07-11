import asyncio, json, logging, mimetypes, os, shutil, subprocess, time
from pathlib import Path
from .db import now

log=logging.getLogger('tvm.downloader')
class UserCancelled(Exception): pass
class DownloadPaused(Exception): pass
class Downloader:
    def __init__(self,db,tg,root:Path,concurrency=2,min_free_gb=10):
        self.db=db; self.tg=tg; self.root=root; self.media=root/'media'; self.temp=root/'temp'; self.thumbs=root/'thumbnails'
        self.concurrency=concurrency; self.reserve=int(min_free_gb*1024**3); self.workers=[]; self.cancelled=set(); self.pause_requested=set(); self.stopping=False
    async def start(self): self.workers=[asyncio.create_task(self.worker(i)) for i in range(self.concurrency)]
    async def stop(self):
        self.stopping=True
        for w in self.workers: w.cancel()
        await asyncio.gather(*self.workers,return_exceptions=True)
    def enqueue(self,item):
        t=now(); safe=Path(item['file_name']).name.replace('\x00','')[:240] or f"video_{item['message_id']}.mp4"; account_id=int(item.get('account_id') or self.tg.active_id)
        try:
            cur=self.db.execute('''INSERT INTO downloads(account_id,channel_id,message_id,channel_title,file_name,total_bytes,status,created_at,updated_at)
              VALUES(?,?,?,?,?,?,'queued',?,?)''',(account_id,int(item['channel_id']),int(item['message_id']),item.get('channel_title',''),safe,int(item.get('size',0)),t,t)); return cur.lastrowid,False
        except Exception:
            old=self.db.one('SELECT id,status FROM downloads WHERE channel_id=? AND message_id=?',(int(item['channel_id']),int(item['message_id']))); return old['id'],True
    async def worker(self,index):
        log.info('下载 worker 已启动 index=%s',index)
        while not self.stopping:
            job=None
            try:
                job=self.db.one("SELECT * FROM downloads WHERE status='queued' ORDER BY id LIMIT 1")
                if not job: await asyncio.sleep(1); continue
                changed=self.db.execute("UPDATE downloads SET status='downloading',error='',updated_at=? WHERE id=? AND status='queued'",(now(),job['id'])).rowcount
                if not changed: await asyncio.sleep(.1); continue
                await self.download(job)
            except asyncio.CancelledError: raise
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
    def retryable(self,e):
        s=str(e)
        return not isinstance(e,(UserCancelled,ValueError)) and not any(x in s for x in ('磁盘','原消息不存在','不可访问'))
    def friendly(self,e):
        s=str(e)
        if '空间' in s: return s
        if isinstance(e,(ConnectionError,TimeoutError,OSError)) or any(x in type(e).__name__.lower() for x in ('timeout','connection','rpc')): return 'Telegram 网络连接中断，可点击重试继续下载'
        return '下载失败，可点击重试继续下载'
    async def download(self,job):
        free=shutil.disk_usage(self.root).free
        if free-self.reserve < max(job['total_bytes'],0):
            self.db.execute("UPDATE downloads SET status='paused',error='磁盘剩余空间不足，任务已暂停',updated_at=? WHERE id=?",(now(),job['id'])); return
        c=await self.tg.get_client(job.get('account_id',1)); entity=await c.get_entity(job['channel_id']); msg=await c.get_messages(entity,ids=job['message_id'])
        if not msg or not msg.video: raise RuntimeError('Telegram 原消息不存在或已不可访问')
        channel_dir=self.media/str(job.get('account_id',1))/str(job['channel_id']); channel_dir.mkdir(parents=True,exist_ok=True)
        final=channel_dir/f"{job['message_id']}_{job['file_name']}"; temp=self.temp/f"{job['id']}.part"; total=int(getattr(msg.video,'size',0) or job['total_bytes'] or 0)
        existing=temp.stat().st_size if temp.exists() else 0
        if total and existing>total: temp.unlink(missing_ok=True); existing=0
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
            with temp.open('ab' if existing else 'wb') as f:
                current=existing
                async for chunk in c.iter_download(msg.video,offset=existing,request_size=512*1024,chunk_size=512*1024,file_size=total or None):
                    if job['id'] in self.cancelled: raise UserCancelled()
                    if job['id'] in self.pause_requested: raise DownloadPaused()
                    f.write(chunk); current+=len(chunk); await progress(current,total)
                f.flush(); os.fsync(f.fileno())
        except UserCancelled:
            temp.unlink(missing_ok=True); self.cancelled.discard(job['id']); self.db.execute("UPDATE downloads SET status='cancelled',speed=0,error='',updated_at=? WHERE id=?",(now(),job['id'])); return
        except DownloadPaused:
            current=temp.stat().st_size if temp.exists() else existing
            self.pause_requested.discard(job['id'])
            self.db.execute("UPDATE downloads SET status='paused',downloaded_bytes=?,speed=0,error='已暂停，临时文件已保留',updated_at=? WHERE id=?",(current,now(),job['id'])); return
        except asyncio.CancelledError:
            current=temp.stat().st_size if temp.exists() else existing
            self.db.execute("UPDATE downloads SET status='queued',downloaded_bytes=?,speed=0,error='服务重启，稍后自动续传',updated_at=? WHERE id=?",(current,now(),job['id'])); return
        if not temp.exists(): raise RuntimeError('未生成下载文件')
        os.replace(temp,final); meta=await asyncio.to_thread(self.probe,final,job['id'])
        self.db.execute('''INSERT OR REPLACE INTO media(download_id,account_id,channel_id,message_id,channel_title,file_name,file_path,thumb_path,size,duration,width,height,mime,caption,message_date,downloaded_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(job['id'],job.get('account_id',1),job['channel_id'],job['message_id'],job['channel_title'],job['file_name'],str(final),meta['thumb'],final.stat().st_size,meta['duration'],meta['width'],meta['height'],mimetypes.guess_type(final.name)[0] or 'application/octet-stream',msg.message or '',msg.date.isoformat(),now()))
        self.db.execute("UPDATE downloads SET status='completed',downloaded_bytes=?,total_bytes=?,speed=0,error='',temp_path='',updated_at=? WHERE id=?",(final.stat().st_size,final.stat().st_size,now(),job['id']))
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
        self.pause_requested.discard(id)
        self.cancelled.add(id)
        changed=self.db.execute("UPDATE downloads SET status='cancelled',updated_at=? WHERE id=? AND status IN ('queued','retrying')",(now(),id)).rowcount
        if changed: self.cancelled.discard(id)
    def pause(self,id):
        row=self.db.one('SELECT status FROM downloads WHERE id=?',(id,))
        if not row: return False
        if row['status']=='downloading':
            self.pause_requested.add(id)
            self.db.execute("UPDATE downloads SET status='pausing',error='正在安全暂停…',updated_at=? WHERE id=?",(now(),id)); return True
        changed=self.db.execute("UPDATE downloads SET status='paused',speed=0,error='已暂停，临时文件已保留',updated_at=? WHERE id=? AND status IN ('queued','retrying')",(now(),id)).rowcount
        return bool(changed)
    def resume(self,id):
        self.pause_requested.discard(id); self.cancelled.discard(id)
        return bool(self.db.execute("UPDATE downloads SET status='queued',speed=0,error='',retry_count=0,updated_at=? WHERE id=? AND status='paused'",(now(),id)).rowcount)
