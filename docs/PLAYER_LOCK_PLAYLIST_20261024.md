# 播放方向锁与选集 · 2026-10-24

## 使用方法与边界

播放器底部工具栏新增锁形按钮，固定进入锁定时的横屏或竖屏方向。锁定后仍可使用播放/暂停、进度条、画面横滑、前后 10 秒、静音、倍速，以及上一集、下一集、选集；关闭播放器、画质、下载、画中画与全屏切换入口暂时收起，解锁后恢复。点击视频仍然只显隐控件，不会暂停。播放空闲时控件收起，选集面板打开时保留。

优先使用浏览器全屏及 Screen Orientation API。该 API 的支持有限，见 [MDN 官方说明](https://developer.mozilla.org/en-US/docs/Web/API/ScreenOrientation/lock)。全屏或方向锁不支持时，使用独立固定播放器布局，旋转内部画面和控件来保持原方向；横滑坐标同步换算。系统状态栏和浏览器外壳仍由手机控制，因此不保证锁住整个操作系统。输入法缩小视口时不当作手机旋转。实体 iPhone Safari 尚未实测。

底部新增上一集、选集、下一集。这里的“集”指已经下载至媒体库的视频，不触发 Telegram 下载：

- 从媒体库进入，按当前搜索、筛选和排序后的列表选择；复用该列表的元数据，避免较早的视频被默认列表上限截断。
- 从频道挑选页进入，沿用当前可见、已下载卡片的顺序。
- 从其他入口进入，仅取当前账号、当前频道的视频，按名称自然排序，例如第 1、2、10 集；不会自动跨账号或频道拼接。
- 选集可以搜索名称，单次显示 100 项，列表更长时使用“显示更多”。首集和末集禁用对应切换按钮；列表失败可重试。非媒体库入口仍受媒体列表接口的返回数量上限约束。

切集复用同一个播放器和 video 元素，保持全屏、锁定、音量、静音、倍速和当前播放/暂停状态，记录各视频的独立进度；新视频默认原画。接口切换失败保留当前视频，快速连续选择忽略过期响应。音频和视频继续使用同一元素的播放时钟。Escape 优先关闭选集，其次解锁，最后关闭播放器。

实现入口：`player-lock.js` 管理方向和生命周期；`player-playlist.js` 管理选集；`premium.js` 在同一播放器切换视频；`player-gestures.js` 换算旋转后的手势坐标。无需修改数据库或 Telegram 账号配置。

## 验证方式

在一次性 `tests/accounts_ui_server.py` 环境运行，使用假账号和真实的 24 秒 H.264/AAC 素材，不挂载生产数据：

```bash
TEST_URL=http://127.0.0.1:8082 PLAYWRIGHT_MODULE=/path/to/playwright/index.mjs node tests/player_lock_playlist_ui.mjs
TEST_URL=http://127.0.0.1:8082 PLAYWRIGHT_MODULE=/path/to/playwright/index.mjs node tests/player_controls_ui.mjs
TEST_URL=http://127.0.0.1:8082 PLAYWRIGHT_MODULE=/path/to/playwright/index.mjs node tests/player_ui.mjs
```

新测试覆盖方向锁调用、API 与全屏不可用时的固定布局、旋转后的真实 CDP 触摸定位、输入法视口、锁定/全屏连续切集、音量倍速/暂停保持、自然排序、账号频道隔离、搜索与首末边界、媒体库顺序和稀疏接口结果、独立进度、失败与快速连续切集、异步锁定结束时清理。方向 API 用桩模拟，实际布局、全屏、视频播放与触摸操作在无头 Chromium 中执行；不能代替实体手机系统方向锁验证。另两组回归原画播放、音画共用播放器、切片预览、横滑、触控防误暂停、明暗主题及全屏。

三组浏览器测试均通过，竖屏锁定和旋转后的选集截图已目检。应用版本 `1be402ae1a10` 已构建并运行于两机；VPS 8080、8084 HTTPS 中转、InstaBox 8081 的八个运行资源与仓库匹配，健康检查及原账号授权正常。通过 HTTPS 中转使用 VPS 的已有视频实测：轻触画面不暂停，底部暂停、原画、49 项选集、锁定中切换与切回、同一播放器和暂停/1.25 倍速保留通过，无页面脚本错误；VPS 两个入口的原文件 Range 附件通过。InstaBox 自身没有已归档媒体，其公网验证覆盖资源、健康和账号，不声称实测该实例的真实视频。

重建应用后两机原账号、管理员/API 配置指纹、Session 授权指纹及除 IMAGE_TAG 外的环境配置一致；SQLite quick_check 为 ok。VPS 原 49 条媒体、49 条下载和 1 条发送记录的标识及稳定字段均保留，媒体文件路径和大小一致；InstaBox 原 1 个账号、0 条媒体/下载保持。后台更新单元均成功，Akile、Komari、1Panel 和 HTTPS 中转的容器/进程未变。备份目录内 `verification.json`、`records-verification.json` 记录主机与数据复核结果。

## 部署与管理

本次升级前两机仓库为 `4ce869de129b`，应用版本为 `6fca686875ab`。目标与数据路径沿用原有独立实例：

| 实例 | 项目目录 | Compose 项目 | 数据路径 |
| --- | --- | --- | --- |
| VPS | `/opt/telegram-video-manager` | `telegram-video-manager` | `/data/telegram-video-manager` |
| InstaBox | `/data/workspace/tg-web-archive` | `tg-web-archive` | 项目下 `data/` |

部署前确认 hostname、资源、容器和端口；工作树必须干净，先备份数据库和 Session，旧镜像单独打回滚标签。只替换本项目 app，重启本项目 nginx，避免其缓存旧容器 IP。不要执行 `down -v` 或恢复旧数据库来回滚界面更新。

VPS：

```bash
cd /opt/telegram-video-manager
git pull --ff-only
docker compose -p telegram-video-manager config --quiet
docker compose -p telegram-video-manager build app
docker compose -p telegram-video-manager up -d --no-deps --force-recreate --wait --wait-timeout 180 app
docker compose -p telegram-video-manager restart nginx
curl -fsS --retry 8 --retry-delay 2 --retry-all-errors http://127.0.0.1:8080/health
```

InstaBox，后台执行时必须保留正确工作目录和 `PWD`：

```bash
cd /data/workspace/tg-web-archive
export PWD=/data/workspace/tg-web-archive
export IMAGE_TAG=$(git rev-parse --short=12 HEAD)
docker compose -p tg-web-archive -f docker-compose.instabox.yml config --quiet
docker compose -p tg-web-archive -f docker-compose.instabox.yml build app
docker compose -p tg-web-archive -f docker-compose.instabox.yml up -d --no-deps --force-recreate --wait --wait-timeout 180 app
# 启动成功后仅同步 .env 中的 IMAGE_TAG；保留其他配置及密码。
docker compose -p tg-web-archive -f docker-compose.instabox.yml restart nginx
curl -fsS --retry 8 --retry-delay 2 --retry-all-errors http://127.0.0.1:8081/health
```

日志及状态分别使用对应 Compose 项目的 `logs --tail 100 app` 和 `ps`；日志只在受保护环境查看，不提交 GitHub。8084 HTTPS 中转继续指向 VPS，无需重建。Akile、Komari、1Panel 与外部保活保持原配置。

## 本次备份与回滚

升级前备份目录权限 700，`.env` 权限 600，包含 SQLite 一致性 backup、Session、配置和镜像/服务清单，不包含大型媒体：

- VPS：`/root/backups/tg-web-archive-player-lock-20261024T023416Z`；旧镜像 `tg-web-archive-vps-rollback:player-lock-20261024`。
- InstaBox：`/data/workspace/tg-web-archive/backups/tg-web-archive-player-lock-20261024T023412Z`；旧镜像 `tg-web-archive-app:rollback-player-lock-20261024`。

VPS 回滚时确认没有未提交修改，切换至 `4ce869de129b`，将回滚镜像标记为 Compose 的 app 镜像，再使用 `--no-build`：

```bash
cd /opt/telegram-video-manager
git switch --detach 4ce869de129b
docker tag tg-web-archive-vps-rollback:player-lock-20261024 telegram-video-manager-app
docker compose -p telegram-video-manager up -d --no-deps --no-build --force-recreate --wait --wait-timeout 180 app
docker compose -p telegram-video-manager restart nginx
curl -fsS --retry 8 --retry-delay 2 --retry-all-errors http://127.0.0.1:8080/health
```

InstaBox 同样切至升级前版本，使用 `IMAGE_TAG=rollback-player-lock-20261024` 和 `--no-build` 重建本项目 app，再重启本项目 nginx 并检查 8081 健康。同步 `.env` 的 IMAGE_TAG，以免下一次操作误启动新镜像。回到新版时先切回 main，再按更新步骤执行。回滚只变更应用，不删除数据目录、下载记录、账号或 Session。

凭据仍只保存在原受保护本地文件和服务器 `.env`/数据目录；不打印、不修改密码，不提交真实配置、数据库、Session、日志或验证 Cookie。
