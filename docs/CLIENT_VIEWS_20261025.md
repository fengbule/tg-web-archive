# 手机、平板、电脑视图与服务器归档

## 使用方式

登录后点击页头的视图按钮，直接选择“手机模式 / 平板模式 / 电脑模式”，或恢复“自动适应”。默认按实际屏幕宽度选择：小于 680px 为手机，680–1179px 为平板，其余为电脑。手动选择保存在当前浏览器的 `nebula-view-mode`，刷新后保留；其他设备可使用自己的模式。电脑上也能主动切到居中的手机视图。

- 手机：单栏、底部五项导航，频道列表 → 视频内容 → 返回频道；返回后原勾选和已加载视频保留。账号管理、聊天、Telegram 收藏夹和设置可通过左上角菜单进入。
- 平板：紧凑图标文字侧栏；频道列表与视频内容并排，减少来回跳转。
- 电脑：完整侧栏和双栏频道工作区，频道列表有独立滚动条，视频卡片连续向下浏览。
- 很窄的实际屏幕即使选了电脑或平板，双栏仍会折成单栏，保证文字和按钮可用；播放器、全屏和方向锁始终依据真实屏幕尺寸。

频道页采用类似聊天客户端的列表和媒体消息布局，保留封面重试、已下载状态、收藏、搜索筛选、勾选、连续加载和任务暂停/续传。切换视图只调整样式，不重建当前页面或视频，已勾选项目、当前播放进度、倍速和音量保持。

## 文件保存位置

频道和未下载收藏中的“下载到服务器”发送 `POST /api/downloads`，文件进入当前实例的服务器下载队列。关闭浏览器不会停止队列。完成后在“服务器媒体库”播放；下载期间可在“服务器下载”暂停、继续和重试。

媒体库卡片的下载图标为“另存原画到手机 / 电脑”，批量按钮为“另存到本机”；它们使用已有附件和 ZIP64 路径，浏览器才会把服务器文件另存到用户设备。两个操作分别存在，默认频道归档不会主动把文件存入手机。

| 实例 | 宿主机媒体路径 | 公网入口 |
| --- | --- | --- |
| VPS | `/data/telegram-video-manager/media/` | `http://84.54.3.25:8080` |
| InstaBox 原生 | `/data/workspace/tg-web-archive/data/media/` | `https://8081-agqv47q5at4mzg6nr336pvg33u.instabox.tech` |
| InstaBox HTTPS 中转 | 文件仍在 VPS 上 | `https://8084-agqv47q5at4mzg6nr336pvg33u.instabox.tech` |

两个原生实例的账号、收藏和文件相互独立；8084 是 VPS 的另一入口。没有改数据库结构、密码、Telegram API/Session、下载连接池、网络调优或数据卷。

## 实现与验证

`client-view.js` 在首次绘制前应用偏好，提供本地存储同步、键盘选择及模式切换；`client-view.css` 使用根节点的 `data-layout`，只重排应用外壳与内容。`channel-browser.js` 保留频道列表和当前视频 DOM，搜索使用请求序号防止旧响应覆盖新列表，下载仍走现有账号隔离接口。修复旧菜单的两个处理器重复切换，移动菜单与背景遮罩由一个处理器管理。

无头测试入口为 `tests/client_view_ui.mjs`。在一次性 `tests/accounts_ui_server.py` 假 Telegram 环境运行，禁止挂载真实数据；测试包含 320/390/768/1024/1440 宽度 × 明暗主题 × 四种模式、刷新保留、键盘、频道返回保留勾选、播放器实例和进度保持、服务器入队及实际文件落盘、浏览器附件保存、消息单双栏。现有 `catalog_ui.mjs`、`favorites_ui.mjs`、`player_ui.mjs`、`player_controls_ui.mjs`、`player_lock_playlist_ui.mjs` 用于回归。会新增素材的测试组之间重启一次性容器，避免互相污染。

手机体验由带触摸事件的无头 Chromium 和截图验证；不把它等同于 iOS/Android 真机验收。

## 本次备份与更新

本次变更前源码为 `d297f3d`，应用为 `ff4c18e`。已在各主机核对身份、端口、容器和资源，创建配置及 SQLite/Session 一致性备份，保留原镜像：

- VPS：`/root/backups/tg-web-archive-client-view-20261025T042750Z`；镜像 `tg-web-archive-vps-rollback:client-view-20261025`。
- InstaBox：`/data/workspace/tg-web-archive/backups/tg-web-archive-client-view-20261025T042741Z`；镜像 `tg-web-archive-app:rollback-client-view-20261025`。

备份目录 700，配置和后台部署日志 600。真实凭据、数据库、会话及日志只在受保护位置，不进入 Git。部署记录与账号/文件保留验收在上线后补记。

VPS 在独立项目内更新：

```bash
cd /opt/telegram-video-manager
git pull --ff-only
docker compose -p telegram-video-manager config --quiet
docker compose -p telegram-video-manager build app
docker compose -p telegram-video-manager up -d --no-deps --force-recreate --wait --wait-timeout 180 app
docker compose -p telegram-video-manager restart nginx
curl -fsS --retry 8 --retry-delay 2 --retry-all-errors http://127.0.0.1:8080/health
```

InstaBox：在 `/data/workspace/tg-web-archive` 中 `git pull --ff-only`，导出 `PWD=/data/workspace/tg-web-archive` 和 `IMAGE_TAG=$(git rev-parse --short=12 HEAD)`；使用 `docker compose -p tg-web-archive -f docker-compose.instabox.yml` 执行 `config --quiet`、`build app`、`up -d --no-deps --force-recreate --wait --wait-timeout 180 app`。成功后只同步 `.env` 中的 IMAGE_TAG，再重启本项目 nginx 并检查 8081 健康。后台运行时指定正确用户和工作目录。不要重启 8084 中转或其他项目。

管理使用各自 Compose 项目的 `ps`、`logs --tail 100 app`、`restart app`。健康接口恢复后再验证静态资源版本、登录授权和 API；Nginx 重启期间可短暂出现 502，使用有上限的重试。浏览器通常刷新即可加载新资源。

## 回滚

确认工作树干净，检出 `d297f3d`。VPS 将保留镜像重新标记为 `telegram-video-manager-app`，用上述独立 Compose 项目 `up -d --no-deps --force-recreate --no-build --wait app`；InstaBox 使用 `IMAGE_TAG=rollback-client-view-20261025` 加 `--no-build` 更新 app，成功后同步 `.env` 标签。重启各自 nginx、核验健康与原登录。

本次只有静态界面变更，回滚不需要恢复数据库。禁止 `down -v` 或删除账号、媒体、下载临时文件和数据卷。Akile、Komari、1Panel、外部保活以及同机其他项目均不在操作范围。既有账号备份/导出方法继续见 [账号迁移说明](THEME_BACKUP_PREVIEW_20261023.md)。
