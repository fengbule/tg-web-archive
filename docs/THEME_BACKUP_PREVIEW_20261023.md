# 明暗主题、账号迁移与拖动预览（2026-10-23）

本次升级承接 [原画播放升级](ORIGINAL_PLAYER_20261023.md)，继续默认原画、单一音视频时钟，保留扫码/API 登录、管理员密码、账号和历史任务。

## 使用

- 顶栏与登录页的太阳/月亮按钮切换明暗主题；首次跟随系统，手动选择保存在本机 `localStorage.nebula-theme`，刷新和下次打开保留。
- 账号管理 → 导出备份，可选一个或多个账号。输入当前管理员密码，另设至少 12 位的备份密码，即可下载 `.nebula` 文件到手机或电脑。
- 账号管理 → 导入账号，选择文件，输入目标服务器管理员密码与备份密码。只新增账号；相同 Telegram auth key 会跳过，现有账号、密码、当前账号不变。导入的授权保持待连接，手动切换后才连接 Telegram。
- 备份包含账号名称、API ID/Hash、生产/测试模式、登录授权；不包含后台密码、网页 Cookie、消息缓存、视频和任务。采用随机 16 字节 salt、PBKDF2-HMAC-SHA256（600,000 次）、Fernet 认证加密。备份不依赖原服务器的配置加密 Key，恢复后按新服务器 Key 重新加密 API 配置。
- `.nebula` 和备份密码需分别妥善保存。迁移时停止旧实例使用该授权；同一个 auth key 在两台服务器同时使用可能被 Telegram 撤销。[Telethon Session 文档](https://docs.telethon.dev/en/stable/concepts/sessions.html) 说明 StringSession 保存的是登录授权；已被撤销的授权不能靠旧备份重新登录。
- 播放器按住进度条、拖动或手机横滑时显示目标时间附近的画面切片。切片是近似预览，精确时间仍用于原画定位。移动时只更新轻量预览，停留 180ms 或松手立即提交最新目标，减少反复请求被放弃的原画分片。播放/暂停状态、播放速度和音画同轨保留。

## 缓存与接口

数据库 `media.preview_status` 为增量列，pending/preparing/ready/failed。重启恢复未完成生成；已完成缓存保留，缓存缺失时重新生成。原画 HLS 准备后、流畅版转码前生成预览，单 worker、单 ffmpeg 线程、仅读关键帧，原视频不改动。

预览存于 `DATA_ROOT/thumbnails/seek-v1/<media_id>/`，每张 JPEG 为 8×8、160×90 小图，每 8 秒一格；超长视频扩大间隔，最多约 900 格。`index.json` 保存间隔、尺寸、格数和切片名称。生成到 `.tmp` 后原子发布；保留至少 2GB 或 MIN_FREE_GB 的磁盘保护线，失败时保留时间预览与正常播放。删除视频同时删除对应预览。

以下接口全部要求后台登录；备份额外重新验证管理员密码，响应不缓存，参数不写日志：

```text
POST /api/accounts/backup/export  {admin_password,backup_password,account_ids?}
POST /api/accounts/backup/import  {admin_password,backup_password,backup:<文件文本>}
GET  /api/media/<id>/preview
GET  /api/media/<id>/preview/sheet-001.jpg
```

导入限制 2MB、100 账号，完整校验格式、加密认证、API 和 Session 后再写入。Session 使用新随机文件名；不接受外部路径或 SQL 数据库。数据库事务失败会回滚并删除本次创建的 Session，不覆盖既有数据。新 Session 权限 600。导入和导出均不创建第二个 Telegram 客户端。

## 更新、管理与回滚

凭据仅保存在本机受保护目录 `D:/VibeCoding/Codex/20261020/output/tg-web-archive/` 和服务器原 `.env` / 数据目录。618HK SSH 凭据沿用 `C:/Users/fengbule/Desktop/618hk.txt`。不要把它们、`.nebula`、Session、数据库、日志提交到 Git。

InstaBox 机器 `m_agqv47q5at4mzg6nr336pvg33u`：

```bash
cd /data/workspace/tg-web-archive
bash scripts/instabox.sh backup
git fetch origin && git merge --ff-only origin/main
bash scripts/instabox.sh deploy
docker compose -p tg-web-archive -f docker-compose.instabox.yml ps
curl -fsS http://127.0.0.1:8081/health
```

该脚本仅更新本项目。端口 8081 与 Akile 3000 隔离，数据为项目内 data，保留原 `.env`。回滚时检出升级前代码并再次 `deploy`；数据库增量列可保留，不必恢复账号库。需恢复备份时先停止本项目，遵循 [InstaBox 备份说明](INSTABOX.md)，不要覆盖服务器其他目录。

618HK VPS：

```bash
cd /opt/telegram-video-manager
umask 077
backup_dir=/root/backups/tg-web-archive-$(date -u +%Y%m%dT%H%M%SZ)
mkdir -m 700 -p "$backup_dir"
cp -p .env "$backup_dir/.env"
git rev-parse HEAD > "$backup_dir/commit"
docker inspect -f '{{.Image}}' telegram-video-manager > "$backup_dir/image"
docker compose stop app
trap 'docker compose start app >/dev/null' EXIT
python3 - "$backup_dir" <<'PY'
import sqlite3,tarfile,sys
from pathlib import Path
root=Path('/data/telegram-video-manager');backup=Path(sys.argv[1])
source=sqlite3.connect(root/'database/app.db');dest=sqlite3.connect(backup/'app.db')
source.backup(dest);dest.close();source.close()
with tarfile.open(backup/'private-data.tar.gz','w:gz') as tar:
    for name in ('session','config','database','thumbnails'):
        tar.add(root/name,arcname=name)
PY
chmod 600 "$backup_dir"/*
docker compose start app
trap - EXIT
printf '%s\n' "$backup_dir" > /root/backups/tg-web-archive-latest-private
# 以上备份含登录授权和配置；视频及未完成 .part 仍在原数据目录。
git fetch origin && git merge --ff-only origin/main
docker compose build app
docker compose up -d --no-deps --force-recreate app
docker compose up -d --wait app
docker compose restart nginx
curl -fsS http://127.0.0.1:8080/health
```

VPS 数据仍为 `/data/telegram-video-manager`。本次升级前为 `3ba4328`，可在工作树干净时按备份 `commit` 回滚代码，保留当前 .env 和数据（包括升级后的新下载）：

```bash
cd /opt/telegram-video-manager
backup_dir=$(cat /root/backups/tg-web-archive-latest-private)
git status --short  # 有修改时先处理，不执行 reset/clean
git switch --detach "$(cat "$backup_dir/commit")"
docker compose build app
docker compose up -d --no-deps --force-recreate app
docker compose up -d --wait app
docker compose restart nginx
curl -fsS http://127.0.0.1:8080/health
```

预览新增列与本次升级前版本兼容；不要重跑 install、改密码或删除卷。仅当明确需要恢复损坏的数据时，停止自己的 app 后先另外备份当前数据，再恢复配套 .env/数据库/Session；恢复旧数据会丢失备份之后的任务和授权。历史 [VPS 部署说明](VPS-618HK.md) 的默认流畅版描述已被后续默认原画版本取代。

## 验证记录

发布前隔离环境：71 项 Python 测试、API 冒烟、依赖漏洞检查通过。无头 Chromium 覆盖：明暗主题首次跟随/切换/刷新记忆，1440/390/320 三尺寸的媒体库/账号/设置布局；加密文件下载、错误管理员密码/备份密码、重复导入；真实 JPEG 预览、触屏横滑/进度条、松手保留最后目标、暂停/恢复、原画渐进加载与音画同步回归。

应用版本 `516600701b99d08b346d81b1266c99723444854b` 已部署两台服务器，镜像代码校验一致；公网健康、登录保护、明暗主题记忆、三尺寸布局、真实 JPEG 切片、原画播放、原画/流畅版 Range 206/416、本机完整附件下载与 ZIP 解压均通过，浏览器脚本错误为 0。

| 测量 | VPS 55 分钟真实视频 | InstaBox 20 秒测试视频 |
| --- | --- | --- |
| 原画跳转并呈现目标帧 | 30:00，6.14 秒 | 12 秒，1.20 秒 |
| 手机拖动显示切片 | 40:00，冷加载 1.08 秒 | 已预载切片，0.03 秒 |

同位置单次对比（10/30/45 分钟）：升级前 6.64/6.39/5.58 秒，升级后 5.58/7.12/6.26 秒。**没有证据证明原画解码跳转显著缩短，不宣称原画秒切**；收益为切片反馈、同张切片内移动无需请求新图片，以及连续移动时不加载已放弃的目标。原画仍受带宽、并发任务和源文件关键帧间隔限制；这些值不是手机所有网络的保证。

VPS 实际生成 414 格、7 张 JPEG，合计 917,838 字节。重启后原画与预览仍就绪，账号仍授权。55 分钟源文件 1,668,231,365 字节，原画分片 664 个；H264 压缩视频切片哈希一致，AAC/H264 同轨，相对音画起点仅差约 15 微秒。

两台升级前后管理员/查看密码哈希、API 密文、Telegram auth key 指纹均一致；原有媒体逐项保留、数据库 quick_check=ok。InstaBox 仍为 1 账号、0 媒体。VPS 验收期间用户新增下载，快照为 1 账号、3 媒体、30 下载、1 发送，原有 1 条媒体仍完整保留；没有用旧数据库覆盖新增内容。Akile 容器 ID/配置哈希/3000 健康、Komari PID（8269/637）、1Panel 启动时间保持一致，保活配置未改。

本次服务器私有备份：InstaBox `backups/tg-web-archive-20261023T030545Z.tar.gz`；VPS `/root/backups/tg-web-archive-20261023T030549Z-seek-upgrade/`。另外实际测试了 InstaBox 正确管理员密码导出，其加密文件与恢复密码分别保存在本机受保护目录，未导入生产账号、未撤销任何真实会话。

待观察：VPS 仍在运行新的下载队列，原画与预览缓存会按单 worker 排队生成；空间不足或特殊编码失败时保留原文件播放和时间预览。原画长距离跳转的链路限制仍存在，切片并不代表对应原画已缓冲。
