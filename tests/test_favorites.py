from concurrent.futures import ThreadPoolExecutor
from app.db import Database, now
from app.favorites import Favorites


def setup(tmp_path):
    db = Database(tmp_path / 'favorites.sqlite'); db.init()
    return db, Favorites(db)


def source(**kwargs):
    return dict(account_id=1, channel_id=42, message_id=7, file_name='第1集.mp4',
                channel_title='剧集', size=1234, duration=24, **kwargs)


def media(db, tmp_path, account=1):
    path = tmp_path / f'clip-{account}.mp4'; path.write_bytes(b'fixture')
    return db.execute('''INSERT INTO media(account_id,channel_id,message_id,channel_title,file_name,
        file_path,size,downloaded_at) VALUES(?,42,7,'剧集','本地名称.mp4',?,7,?)''', (account, str(path), now())).lastrowid


def test_idempotent_account_scoped_and_marks(tmp_path):
    db, favorites = setup(tmp_path)
    db.execute("INSERT INTO accounts(label,session_name,created_at) VALUES('第二账号','two',?)", (now(),))
    first = source(); second = {**first, 'account_id': 2}
    for _ in range(3): favorites.add(first, 1)
    favorites.add(second, 1)
    assert favorites.listing()['total'] == 2
    assert all(item['is_favorite'] for item in favorites.mark([first, second]))
    favorites.remove(1, 42, 7); favorites.remove(1, 42, 7)
    assert not favorites.mark([first])[0]['is_favorite']
    assert favorites.mark([second])[0]['is_favorite']
    db.close()


def test_restart_and_redownload_relink_without_losing_bookmark(tmp_path):
    db, favorites = setup(tmp_path)
    favorites.add(source(), 1)
    mid = media(db, tmp_path)
    assert favorites.listing()['items'][0]['media_id'] == mid
    favorites.add({'media_id': mid, 'account_id': 999, 'file_name': 'untrusted'}, 999)
    assert favorites.listing()['total'] == 1
    assert favorites.listing()['items'][0]['file_name'] == '本地名称.mp4'
    db.execute('DELETE FROM media WHERE id=?', (mid,))
    assert favorites.listing(state='pending')['total'] == 1
    newer = media(db, tmp_path)
    db.close()
    restarted = Database(tmp_path / 'favorites.sqlite'); restarted.init()
    result = Favorites(restarted).listing(state='downloaded')
    assert result['total'] == 1 and result['items'][0]['media_id'] == newer
    assert restarted.one('SELECT count(*) n FROM downloads')['n'] == 0
    assert restarted.one('SELECT count(*) n FROM outbox')['n'] == 0
    restarted.close()


def test_pagination_search_filters_and_existing_schema(tmp_path):
    db, favorites = setup(tmp_path)
    for message in range(1, 106): favorites.add({**source(), 'message_id': message, 'file_name': f'片段{message:03}.mp4'}, 1)
    local = media(db, tmp_path)
    one = favorites.listing(limit=60); two = favorites.listing(offset=one['next_offset'], limit=60)
    assert one['total'] == 105 and one['has_more'] and len(two['items']) == 45 and not two['has_more']
    assert len({x['favorite_id'] for x in one['items'] + two['items']}) == 105
    assert favorites.listing(state='downloaded')['items'][0]['media_id'] == local
    assert favorites.listing(state='pending')['total'] == 104
    assert favorites.listing(account_id=2)['total'] == 0
    assert favorites.listing(q="' OR 1=1 --")['total'] == 0
    assert favorites.listing(q='本地名称')['total'] == 1
    assert favorites.listing(sort='name')['items'][0]['file_name'] == '本地名称.mp4'
    assert favorites.listing(sort='name')['items'][1]['file_name'] == '片段001.mp4'
    # Repeated initialization must not replace existing accounts, downloads or media.
    db.init(); assert db.one('SELECT id FROM media')['id'] == local
    assert favorites.listing()['total'] == 105
    db.close()


def test_parallel_double_clicks_create_only_one_record(tmp_path):
    db, favorites = setup(tmp_path)
    def save(_):
        try: return favorites.add(source(), 1)
        finally: db.close()
    with ThreadPoolExecutor(max_workers=6) as pool: assert all(pool.map(save, range(12)))
    assert favorites.listing()['total'] == 1
    db.close()

def test_caption_saved_searched_and_local_caption_preferred_without_renaming(tmp_path):
    db,favorites=setup(tmp_path)
    item={**source(),'caption':'原 TG 标题\n完整说明'}
    favorites.add(item,1)
    assert favorites.listing(q='TG 标题')['items'][0]['caption']==item['caption']
    mid=media(db,tmp_path)
    db.execute('UPDATE media SET caption=? WHERE id=?',('下载时的原始说明',mid))
    row=favorites.listing(q='下载时')['items'][0]
    assert row['caption']=='下载时的原始说明' and row['file_name']=='本地名称.mp4'
    db.close();db=Database(tmp_path/'favorites.sqlite');db.init()
    assert Favorites(db).listing()['items'][0]['caption']=='下载时的原始说明'
    db.close()
