# 一键视频收藏 · 2026-10-24

## 使用

频道挑选页封面右上角、媒体库/最近归档卡片、播放器标题栏均有星形按钮。点击后星标变亮并提示已收藏，再点即可取消；保存失败保持原状态并提示重试。播放中和锁定状态下也能收藏，不覆盖视频中央。

电脑侧栏的“视频收藏夹”和手机底部“收藏”进入独立页面，可搜索名称/频道，按账号、已下载/待下载筛选，按收藏时间或名称排序。每次读取 60 项，底部加载更多。已下载视频可以播放和下载到本机；未下载的视频先保存来源记录，之后主动点击“下载视频”，支持继续暂停任务和重试。下载完成后收藏自动关联本地媒体。收藏入口不需要 Telegram 当前在线。

原来的“Telegram 收藏夹”仍可从侧栏或视频收藏页工具栏进入，消息收发和原文件上传流程保留。点击视频星标只保存小型来源记录，不自动上传至 Telegram，也不自动下载视频，不新增下载带宽占用。

收藏保存在当前实例的数据库，可在手机、电脑登录同一服务器查看。VPS 与 InstaBox 的数据独立，不会自动跨服务器同步。账号以来源账号区分；同账号同频道同消息不会重复收藏。媒体重命名后显示新名称；删除媒体保留收藏来源，重新下载时会关联新媒体 ID。原账号移除后收藏记录保留，已有本地视频仍可播放；重新下载需要有效的来源账号及权限。

从收藏页播放时，上一集/下一集和选集沿用当前已加载、已下载收藏的顺序；不自动下载其他收藏。原画、方向锁和切集状态保留的行为沿用播放器说明。

## 数据与接口

启动时通过 `CREATE TABLE IF NOT EXISTS` 增加 `favorites` 表，以 `(account_id,channel_id,message_id)` 唯一索引去重，另建收藏时间索引。不重建已有账号、媒体、任务或 Session，不改变密码；取消收藏只删除收藏记录。

- `GET /api/favorites`：`q`、`account_id`、`state=all|downloaded|pending`、`sort=recent|name`、`offset`、`limit`（最多 100）；返回 `items/total/has_more/next_offset`。
- `PUT /api/favorites`：本地视频传 `media_id`，服务器读取真实来源；频道视频传账号/频道/消息、名称及有限长度的展示信息。重复调用幂等，不改变原收藏时间。
- `DELETE /api/favorites/{account_id}/{channel_id}/{message_id}`：幂等取消。

全部接口复用现有管理员登录鉴权，收藏列表禁用公共缓存；文本输出转义。媒体与频道列表批量查询收藏状态，播放器详情返回星标状态，不增加视频流/分片接口的收藏查询。前端同来源按钮在请求期间禁用，成功后同步当前页面的所有星标。

实现为 `app/favorites.py`、`app/static/favorites.js`、`favorites.css`；`db.py` 增量建表；原导航、卡片和播放器添加入口。备份或完整迁移时对主数据库 `database/app.db` 使用 SQLite backup，收藏随主库保存；仅导出账号 Session 的加密包不包含视频收藏。不要在 SQLite 写入期间只复制 `.db` 文件而遗漏 WAL。

## 验证

```bash
python -m pytest tests/test_favorites.py tests/test_core.py tests/test_catalog.py tests/test_accounts.py tests/test_account_backup.py -q
PYTHONPATH=. python tests/favorites_api_smoke.py
PYTHONPATH=. python tests/api_smoke.py
```

新测试覆盖重复/并发添加、账号隔离、分页/搜索/筛选、删除和重下载关联、主库重开、新 Python 进程重新载入收藏、参数校验、未登录拒绝和不产生上传下载副作用。使用临时数据库及测试凭据，不连接真实 Telegram。

以 `tests/accounts_ui_server.py` 启动一次性假账号/真实音视频环境，再运行：

```bash
TEST_URL=http://127.0.0.1:8082 PLAYWRIGHT_MODULE=/path/to/playwright/index.mjs node tests/favorites_ui.mjs
```

覆盖一键收藏、失败重试、重复点击、网页刷新持久化、频道/媒体库/播放器同步、待下载收藏主动入队后关联媒体、搜索筛选、文本转义、手机导航及 320/390px/桌面明暗主题。此测试会下载假素材，运行其他依赖初始素材数量的浏览器测试前，须重启一次性测试环境以重新生成假数据；不能连接生产数据库。另回归 `player_lock_playlist_ui.mjs`、`player_controls_ui.mjs`、`player_ui.mjs` 和 `catalog_ui.mjs`。

## 双实例部署与回滚

升级前仓库为 `1630396eebde`，运行应用为 `1be402ae1a10`。主机、目录、端口及独立 Compose 项目保持：VPS `/opt/telegram-video-manager`、`telegram-video-manager`、8080；InstaBox `/data/workspace/tg-web-archive`、`tg-web-archive`、8081；8084 中转仍指向 VPS。已核对主机身份、容器、磁盘余量和入口健康。

本次升级前备份（权限 700，配置 600，SQLite 一致性备份及 Session）：

- VPS：`/root/backups/tg-web-archive-favorites-20261024T030844Z`；回滚镜像 `tg-web-archive-vps-rollback:favorites-20261024`。
- InstaBox：`/data/workspace/tg-web-archive/backups/tg-web-archive-favorites-20261024T030841Z`；回滚镜像 `tg-web-archive-app:rollback-favorites-20261024`。

VPS 只更新本项目：

```bash
cd /opt/telegram-video-manager
git pull --ff-only
docker compose -p telegram-video-manager config --quiet
docker compose -p telegram-video-manager build app
docker compose -p telegram-video-manager up -d --no-deps --force-recreate --wait --wait-timeout 180 app
docker compose -p telegram-video-manager restart nginx
curl -fsS --retry 8 --retry-delay 2 --retry-all-errors http://127.0.0.1:8080/health
```

InstaBox 在正确工作目录导出 `PWD=/data/workspace/tg-web-archive` 与 `IMAGE_TAG=$(git rev-parse --short=12 HEAD)`，使用 `docker compose -p tg-web-archive -f docker-compose.instabox.yml` 的 `config --quiet`、`build app`、`up -d --no-deps --force-recreate --wait --wait-timeout 180 app`，成功后仅同步 `.env` 的 IMAGE_TAG，再 `restart nginx`、检查 8081 健康。后台更新不抢占桌面焦点。查看状态/日志使用对应项目 `ps`、`logs --tail 100 app`，日志不提交 GitHub。

回滚前确认工作树干净，切至 `1630396eebde`；VPS 将旧镜像重新标记为 `telegram-video-manager-app`，以 `--no-build` 只重建 app；InstaBox 指定 `IMAGE_TAG=rollback-favorites-20261024` 加 `--no-build` 只重建 app，同步 .env 标签。重启各自 nginx 并检查健康。旧版会忽略新增 favorites 表，无需恢复数据库，已有收藏留在主库，重新升级后可见。不要执行 `down -v`，不要删除账号、数据卷、媒体或 `.part`。保留原密码、API/Session，Akile、Komari、1Panel 与外部保活不在更新范围。
