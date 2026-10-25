"""Small source bookmarks, independent of media files and Telegram uploads."""
from .db import now


class Favorites:
    def __init__(self, db):
        self.db = db

    def add(self, item, active_account):
        item = dict(item)
        media_id = item.get('media_id')
        if media_id is not None:
            media = self.db.one('SELECT * FROM media WHERE id=?', (media_id,))
            if not media:
                raise LookupError('本地视频不存在')
            item = {**media, 'has_thumbnail': bool(media['thumb_path'])}
        account = item.get('account_id') or active_account
        if media_id is None and not self.db.one('SELECT id FROM accounts WHERE id=?', (account,)):
            raise ValueError('Telegram 账号不存在')
        if not item.get('channel_id') or not item.get('message_id') or not item.get('file_name', '').strip():
            raise ValueError('缺少视频来源或名称，请刷新列表重试')
        values = (account, item['channel_id'], item['message_id'], item.get('channel_title', ''),
                  item['file_name'], item.get('size', 0), item.get('duration', 0),
                  item.get('width', 0), item.get('height', 0), int(bool(item.get('has_thumbnail'))), now(),item.get('caption',''))
        self.db.execute('''INSERT INTO favorites(account_id,channel_id,message_id,channel_title,file_name,
            size,duration,width,height,has_thumbnail,created_at,caption) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(account_id,channel_id,message_id) DO NOTHING''', values)
        return {'is_favorite': True, 'account_id': account, 'channel_id': item['channel_id'], 'message_id': item['message_id']}

    def remove(self, account, channel, message):
        self.db.execute('DELETE FROM favorites WHERE account_id=? AND channel_id=? AND message_id=?', (account, channel, message))
        return {'is_favorite': False, 'account_id': account, 'channel_id': channel, 'message_id': message}

    def mark(self, items, account=None):
        if not items:
            return items
        keys = [(int(item.get('account_id') or account or 1), int(item['channel_id']), int(item['message_id'])) for item in items]
        marks = ','.join('(?,?,?)' for _ in keys)
        found = {tuple(row[key] for key in ('account_id', 'channel_id', 'message_id')) for row in self.db.all(
            f'SELECT account_id,channel_id,message_id FROM favorites WHERE (account_id,channel_id,message_id) IN ({marks})',
            tuple(value for key in keys for value in key))}
        for item, key in zip(items, keys):
            item['is_favorite'] = key in found
        return items

    def listing(self, q='', account_id=None, state='all', sort='recent', offset=0, limit=60):
        where, args = [], []
        if q:
            where.append('(COALESCE(m.file_name,f.file_name) LIKE ? OR f.channel_title LIKE ? OR COALESCE(NULLIF(m.caption,\'\'),f.caption) LIKE ?)')
            args.extend(['%' + q + '%'] * 3)
        if account_id is not None:
            where.append('f.account_id=?'); args.append(account_id)
        if state == 'downloaded':
            where.append('m.id IS NOT NULL')
        elif state == 'pending':
            where.append('m.id IS NULL')
        joins = ''' FROM favorites f
            LEFT JOIN media m ON (m.account_id=f.account_id AND m.channel_id=f.channel_id AND m.message_id=f.message_id)
            LEFT JOIN downloads d ON (d.account_id=f.account_id AND d.channel_id=f.channel_id AND d.message_id=f.message_id)
            LEFT JOIN accounts a ON a.id=f.account_id'''
        clause = ' WHERE ' + ' AND '.join(where) if where else ''
        total = self.db.one('SELECT count(*) n' + joins + clause, args)['n']
        order = 'COALESCE(m.file_name,f.file_name) COLLATE NOCASE,f.id DESC' if sort == 'name' else 'f.created_at DESC,f.id DESC'
        rows = self.db.all('''SELECT f.id AS favorite_id,f.account_id,f.channel_id,f.message_id,f.created_at,
            COALESCE(m.file_name,f.file_name) AS file_name,f.channel_title,
            COALESCE(m.size,f.size) AS size,COALESCE(m.duration,f.duration) AS duration,
            COALESCE(m.width,f.width) AS width,COALESCE(m.height,f.height) AS height,
            f.has_thumbnail,COALESCE(NULLIF(m.caption,''),f.caption) AS caption,a.label AS account_label,m.id AS media_id,m.thumb_path,
            m.smooth_status,m.smooth_path,m.smooth_size,d.id AS download_id,d.status AS download_status
            ''' + joins + clause + ' ORDER BY ' + order + ' LIMIT ? OFFSET ?', [*args, limit, offset])
        for row in rows:
            row['is_favorite'] = True
            row['downloaded'] = row['media_id'] is not None
        return {'items': rows, 'total': total, 'next_offset': offset + len(rows), 'has_more': offset + len(rows) < total}
