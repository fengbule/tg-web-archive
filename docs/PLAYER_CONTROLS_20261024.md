# 播放器触控修复 · 2026-10-24

## 交互

- 点击或轻触视频画面只显示/隐藏控制栏，保持原有播放或暂停状态。暂停时轻触画面也不会开始播放。
- 移除覆盖画面中央的播放/暂停和前后跳转按钮，统一放到底部。手机竖屏将播放操作和其他工具分成两排，触控按钮至少 44px。
- 播放时控制栏空闲 3 秒自动隐藏；暂停、按住进度条、鼠标停在控制栏或键盘聚焦控件时保持可见。鼠标移动或轻触画面可以再次显示。
- 普通模式显隐控制栏不改变视频尺寸或位置；自定义全屏模式下控件贴近上下边缘，闲置时收起，视频使用完整画面。浏览器接管的原生视频全屏仍遵循浏览器自身行为。
- 保留空格播放/暂停、方向键定位、F 全屏、M 静音，以及拖动切片预览、横滑定位、原画默认和单一音视频时钟。
- 关闭播放器时清理显隐计时器和全局事件。CSS 与脚本版本号已更新，刷新页面可加载新资源。

实现入口：`app/static/player-controls.js` 负责显隐；`premium.js` 负责播放按钮和播放器生命周期；`style.css` 负责布局。应用数据、Telegram 登录和下载参数均无需迁移。

## 验证

使用 `tests/accounts_ui_server.py` 的一次性假账号和真实 24 秒音视频素材，监听回环地址 8082，不挂载生产数据。运行：

```bash
TEST_URL=http://127.0.0.1:8082 PLAYWRIGHT_MODULE=/path/to/playwright/index.mjs \
  node tests/player_controls_ui.mjs
TEST_URL=http://127.0.0.1:8082 PLAYWRIGHT_MODULE=/path/to/playwright/index.mjs \
  node tests/player_ui.mjs
```

前者覆盖鼠标与真实 CDP 触摸、暂停状态保持、320/390px 明暗主题、按钮不覆盖画面、显隐不跳动、自动隐藏、长按进度条、键盘聚焦、自定义全屏及关闭重开。后者回归原画 HLS、渐进起播、拖动预览、横滑与进度条触控、画质切换和音视频共用播放器。测试使用无头 Chromium；并非实体手机 Safari 的实测结论。

## 双实例更新与回滚

现有部署位置保持不变：VPS `/opt/telegram-video-manager`（Compose 项目 `telegram-video-manager`），InstaBox `/data/workspace/tg-web-archive`（项目 `tg-web-archive`）。8084 HTTPS 中转继续指向 VPS，更新 VPS 应用即可同步提供新页面。

部署前确认机器身份、工作树无未提交修改，记录镜像 ID，并将旧镜像打上本次回滚标签；备份 `.env`、数据库和 Session 到服务器受保护目录，不能提交仓库。数据库备份使用 SQLite backup，而非在写入时直接复制主库文件。只更新本应用的 app 和 nginx 服务。

VPS 更新：

```bash
cd /opt/telegram-video-manager
git pull --ff-only
docker compose -p telegram-video-manager build app
docker compose -p telegram-video-manager up -d --no-deps --force-recreate --wait --wait-timeout 180 app
docker compose -p telegram-video-manager restart nginx
curl -fsS http://127.0.0.1:8080/health
```

InstaBox 按原部署入口更新：

```bash
cd /data/workspace/tg-web-archive
git pull --ff-only
bash scripts/instabox.sh deploy
curl -fsS http://127.0.0.1:8081/health
```

也可指定 `IMAGE_TAG=$(git rev-parse --short=12 HEAD)`，使用独立 Compose 文件只构建/替换 app，然后重启该项目的 nginx，避免拉取和变更其他镜像。保留 `.env` 的原值，只同步 `IMAGE_TAG`。

本次升级前源码为 `db1182a`、运行应用为 `04ac491`。服务器上的旧镜像标签分别为 `tg-web-archive-vps-rollback:player-controls-20261024` 和 `tg-web-archive-app:rollback-player-controls-20261024`。回滚前确认工作树干净，再切至 `db1182a`；VPS 将旧镜像重新标记为 Compose 的 app 镜像后用 `--no-build` 重建 app；InstaBox 使用 `IMAGE_TAG=rollback-player-controls-20261024` 加 `--no-build` 重建 app。随后重启对应 nginx 并检查健康接口。回滚无需恢复数据库或删除数据卷。

本次实际备份目录（仅服务器本地，权限 700）：

- VPS：`/root/backups/tg-web-archive-player-controls-20261024T015553Z`
- InstaBox：`/data/workspace/tg-web-archive/backups/tg-web-archive-player-controls-20261024T015604Z`

其中 `.env` 权限为 600；包含 SQLite 一致性备份、Session 备份与不含秘密值的镜像/服务清单，不包含大型视频文件。

保留原账号、密码、Session、正式媒体、下载记录和 `.part`；不运行 `down -v`、初始化、账号退出或删除操作。Akile、Komari、1Panel 和外部保活不属于本次部署范围。
