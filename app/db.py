import sqlite3, threading, time, re
from pathlib import Path
from datetime import datetime, timezone

class Database:
    def __init__(self, path: Path):
        self.path=path; self.local=threading.local(); self.lock=threading.RLock()
    def conn(self):
        c=getattr(self.local,'c',None)
        if c is None:
            c=sqlite3.connect(self.path,check_same_thread=False,timeout=30)
            c.row_factory=sqlite3.Row; c.execute('PRAGMA journal_mode=WAL'); c.execute('PRAGMA foreign_keys=ON'); c.execute('PRAGMA busy_timeout=30000')
            self.local.c=c
        return c
    def init(self):
        with self.lock:
            c=self.conn(); c.executescript('''
        CREATE TABLE IF NOT EXISTS config(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS accounts(
          id INTEGER PRIMARY KEY AUTOINCREMENT,label TEXT NOT NULL,session_name TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS downloads(
          id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id INTEGER NOT NULL,message_id INTEGER NOT NULL,
          channel_title TEXT NOT NULL DEFAULT '',file_name TEXT NOT NULL,total_bytes INTEGER NOT NULL DEFAULT 0,
          downloaded_bytes INTEGER NOT NULL DEFAULT 0,speed REAL NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'queued',
          retry_count INTEGER NOT NULL DEFAULT 0,
          error TEXT NOT NULL DEFAULT '',temp_path TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
          account_id INTEGER NOT NULL DEFAULT 1,UNIQUE(account_id,channel_id,message_id));
        CREATE TABLE IF NOT EXISTS media(
          id INTEGER PRIMARY KEY AUTOINCREMENT,download_id INTEGER UNIQUE,channel_id INTEGER NOT NULL,message_id INTEGER NOT NULL,
          channel_title TEXT NOT NULL,file_name TEXT NOT NULL,file_path TEXT NOT NULL UNIQUE,thumb_path TEXT NOT NULL DEFAULT '',
          size INTEGER NOT NULL,duration REAL NOT NULL DEFAULT 0,width INTEGER NOT NULL DEFAULT 0,height INTEGER NOT NULL DEFAULT 0,
          mime TEXT NOT NULL DEFAULT 'video/mp4',caption TEXT NOT NULL DEFAULT '',message_date TEXT NOT NULL DEFAULT '',
          downloaded_at TEXT NOT NULL,account_id INTEGER NOT NULL DEFAULT 1,
          faststart INTEGER NOT NULL DEFAULT 0,smooth_path TEXT NOT NULL DEFAULT '',
          smooth_status TEXT NOT NULL DEFAULT 'idle',smooth_progress REAL NOT NULL DEFAULT 0,
          smooth_error TEXT NOT NULL DEFAULT '',smooth_size INTEGER NOT NULL DEFAULT 0,
          FOREIGN KEY(download_id) REFERENCES downloads(id) ON DELETE SET NULL,UNIQUE(account_id,channel_id,message_id));
        CREATE TABLE IF NOT EXISTS outbox(
          id INTEGER PRIMARY KEY AUTOINCREMENT,account_id INTEGER NOT NULL,peer_id INTEGER NOT NULL,
          media_id INTEGER NOT NULL,caption TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'queued',
          uploaded_bytes INTEGER NOT NULL DEFAULT 0,total_bytes INTEGER NOT NULL DEFAULT 0,
          telegram_message_id INTEGER,error TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
          FOREIGN KEY(media_id) REFERENCES media(id) ON DELETE CASCADE);
        CREATE INDEX IF NOT EXISTS idx_download_status ON downloads(status);
        CREATE INDEX IF NOT EXISTS idx_media_channel ON media(channel_id);
        CREATE INDEX IF NOT EXISTS idx_outbox_status ON outbox(status);
        ''')
            for table,column,decl in [('downloads','account_id','INTEGER NOT NULL DEFAULT 1'),('downloads','retry_count','INTEGER NOT NULL DEFAULT 0'),('media','account_id','INTEGER NOT NULL DEFAULT 1'),
                                      ('media','faststart','INTEGER NOT NULL DEFAULT 0'),('media','smooth_path',"TEXT NOT NULL DEFAULT ''"),
                                      ('media','smooth_status',"TEXT NOT NULL DEFAULT 'idle'"),('media','smooth_progress','REAL NOT NULL DEFAULT 0'),
                                      ('media','smooth_error',"TEXT NOT NULL DEFAULT ''"),('media','smooth_size','INTEGER NOT NULL DEFAULT 0'),
                                      ('outbox','telegram_message_id','INTEGER')]:
                cols={x['name'] for x in c.execute(f'PRAGMA table_info({table})').fetchall()}
                if column not in cols: c.execute(f'ALTER TABLE {table} ADD COLUMN {column} {decl}')
            if not c.execute('SELECT 1 FROM accounts LIMIT 1').fetchone():
                c.execute("INSERT INTO accounts(id,label,session_name,created_at) VALUES(1,'账号 1','account',?)",(now(),))
            c.commit()
            self._scope_account_uniqueness(c)
    def _scope_account_uniqueness(self,c):
        """Preserve existing IDs, files and foreign keys when upgrading v1 data."""
        tables=[]
        for table in ('downloads','media'):
            sql=c.execute('SELECT sql FROM sqlite_master WHERE type=\'table\' AND name=?',(table,)).fetchone()['sql']
            updated=re.sub(r'UNIQUE\s*\(\s*channel_id\s*,\s*message_id\s*\)', 'UNIQUE(account_id,channel_id,message_id)',sql,flags=re.I)
            if updated!=sql: tables.append((table,updated))
        if not tables: return
        c.execute('PRAGMA foreign_keys=OFF')
        try:
            c.execute('BEGIN IMMEDIATE')
            for table,sql in tables:
                seq=c.execute('SELECT seq FROM sqlite_sequence WHERE name=?',(table,)).fetchone()
                replacement=table+'_account_scoped'
                sql=re.sub(r'^(CREATE TABLE\s+)(?:"?'+table+r'"?)',r'\1'+replacement,sql,count=1,flags=re.I)
                c.execute(sql)
                columns=','.join('"'+x['name']+'"' for x in c.execute(f'PRAGMA table_info({table})'))
                c.execute(f'INSERT INTO {replacement}({columns}) SELECT {columns} FROM {table}')
                c.execute(f'DROP TABLE {table}')
                c.execute(f'ALTER TABLE {replacement} RENAME TO {table}')
                if seq: c.execute('UPDATE sqlite_sequence SET seq=max(seq,?) WHERE name=?',(seq['seq'],table))
            c.execute('CREATE INDEX IF NOT EXISTS idx_download_status ON downloads(status)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_media_channel ON media(channel_id)')
            if c.execute('PRAGMA foreign_key_check').fetchone(): raise RuntimeError('账号数据迁移外键检查失败')
            c.commit()
        except Exception:
            c.rollback(); raise
        finally:
            c.execute('PRAGMA foreign_keys=ON')
    def recover_interrupted(self):
        """Recover jobs only when the real web-service lifespan starts.

        Keeping this out of schema initialization prevents maintenance scripts or
        CLI imports from changing the state of a job owned by the running server.
        """
        self.execute("UPDATE downloads SET status='queued',error='服务重启后自动续传' WHERE status IN ('downloading','retrying','pausing')")
        self.execute("UPDATE outbox SET status='queued',error='服务重启后自动继续发送' WHERE status='uploading'")
    def execute(self,sql,args=()):
        with self.lock:
            c=self.conn()
            for attempt in range(6):
                try:
                    cur=c.execute(sql,args); c.commit(); return cur
                except sqlite3.OperationalError as e:
                    c.rollback()
                    if 'locked' not in str(e).lower() or attempt==5: raise
                    time.sleep(.05*(attempt+1))
    def all(self,sql,args=()):
        with self.lock: return [dict(x) for x in self.conn().execute(sql,args).fetchall()]
    def one(self,sql,args=()):
        with self.lock: x=self.conn().execute(sql,args).fetchone(); return dict(x) if x else None
    def close(self):
        with self.lock:
            c=getattr(self.local,'c',None)
            if c is not None:
                c.close(); self.local.c=None

def now(): return datetime.now(timezone.utc).isoformat()
