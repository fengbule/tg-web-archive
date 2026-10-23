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
# 更新前先停止自己的 app，备份 .env、SQLite 与 Session/config，再启动 app。
# 沿用 /root/backups/tg-web-archive-latest-private 指向的本次私有备份。
git fetch origin && git merge --ff-only origin/main
docker compose build app
docker compose up -d --no-deps --force-recreate app
docker compose up -d --wait app
docker compose restart nginx
curl -fsS http://127.0.0.1:8080/health
```

VPS 数据仍为 `/data/telegram-video-manager`。回滚到备份 `commit` 对应版本重新构建；也可将备份 `image` 对应镜像标记为 Compose app 镜像后 `up --no-build`。保留当前 .env 和数据，预览新增列不会影响旧版本；不要重跑 install、改密码或删除卷。详细命令见 [VPS 部署说明](VPS-618HK.md)。

## 验证记录

发布前隔离环境：71 项 Python 测试、API 冒烟、依赖漏洞检查通过。无头 Chromium 覆盖：明暗主题首次跟随/切换/刷新记忆，1440/390/320 三尺寸的媒体库/账号/设置布局；加密文件下载、错误管理员密码/备份密码、重复导入；真实 JPEG 预览、触屏横滑/进度条、松手保留最后目标、暂停/恢复、原画渐进加载与音画同步回归。

公网部署、真实长视频跳转测量与数据保留结果在实际验证后补充。切片预览与原画解码耗时分开测量；原画跳转仍受公网带宽、浏览器缓冲和源文件关键帧间隔限制。
