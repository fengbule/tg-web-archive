# 原画播放器、手机拖动与音画同步

本次升级取代此前默认 480P、缓冲自动降级的策略。所有入口默认原画，只有明确手动选择流畅版才切换。原有账号、密码、API 配置和正式媒体保留。

## 播放与界面

- H.264/HEVC + AAC 媒体后台生成 HLS/fMP4 原画缓存，`-c copy` 保留原始编码，按关键帧分片，目标每段 4 秒。拖动后只获取目标附近的分片，不从文件开头顺序读取。
- 视频与第一路音频复用在同一 fMP4 分片，保留相对时间戳，使用同一个 `<video>` 时钟与 `currentTime`；没有两个独立播放器追赶进度。原文件多音轨仍完整保留供下载。
- Safari 优先使用原生 HLS，支持 MediaSource 的浏览器使用本地打包的 HLS.js 1.7.3。缓存未就绪、不兼容编码、空间不足或 HLS 错误时改为原画文件 Range 播放，不偷偷降低画质。
- 拖动时立即显示目标时间，最多每 120ms 提交一次定位；松手强制提交最后位置。拖动前暂停则继续暂停，原来播放则松手恢复。
- 手机进度条触控高度 52px，常用按钮至少 44px。视频区域横滑可精细定位（全宽最多移动 120 秒），保留竖向滚动手势；提供 ±10 秒、倍速、全屏和本机下载。
- 调整为石墨色背景、安静的边框、可读字号与统一按钮；手机播放器使用底部面板，减少大面积空黑和拥挤控件。媒体库突出原画播放和下载。

原画是否立即起播仍取决于网络、原编码与关键帧间隔。源文件长 GOP 会产生长于 4 秒的分片；不重编码就不能凭空增加关键帧。HEVC 能否播放由浏览器和设备解码器决定，原文件下载始终保留。

## 缓存、数据与排障

数据库仅新增 `original_hls_status` / `original_hls_error` 两列，重复启动安全；旧行默认 pending，后台逐条生成。状态为 pending/preparing/ready/unsupported/failed。中断的 preparing 重启后重新排队。

缓存路径为持久化数据根的 `media/.streams/<整数媒体ID>/`，临时生成到 `<ID>.tmp`，完整后原子发布。鉴权 API `/api/media/<ID>/playback` 返回播放入口；`/api/media/<ID>/hls/{index.m3u8,init.mp4,segment-*.m4s}` 仅允许固定文件名，Nginx 内部文件路由不能从公网直接访问。下载仍读取原媒体文件。

缓存约再占用一份原文件大小；生成前要求剩余空间超过 `max(2 GiB, MIN_FREE_GB)` 加原文件的 1.05 倍，过程中继续检查保护线。失败保留原文件并回退直连。删除媒体时一并清理其缓存；不删除账号或会话。大量旧媒体首次升级会有磁盘读取和写入负载。

如需重试 failed 缓存，先检查空间与 FFmpeg 错误，再通过本项目容器在数据库中仅将目标媒体 `original_hls_status` 设为 pending（同时清空该行 original_hls_error）；不要修改文件路径、账号、Session 或下载记录。不兼容编码不应反复重试。ready 缓存如被手工清理，也需将对应行重新设为 pending。

## 部署与回滚

| 目标 | 项目 / 数据 / 入口 | 本轮更新前备份 |
| --- | --- | --- |
| 香港 VPS | `/opt/telegram-video-manager` / `/data/telegram-video-manager` / `http://84.54.3.25:8080` | `/root/backups/tg-web-archive-20261023T012535Z-seek-upgrade` |
| InstaBox | `/data/workspace/tg-web-archive` / 项目内 `data` / 独立 8081 HTTPS | 项目内 `backups/tg-web-archive-20261023T012533Z.tar.gz` |

更新保持工作树干净，先备份，然后 `git fetch origin && git merge --ff-only origin/main`。VPS 执行 `docker compose build app`、`docker compose up -d --no-deps --force-recreate app`，应用 healthy 后重启本项目 `nginx`，检查 `/health`。InstaBox 执行 `bash scripts/instabox.sh deploy`。不运行首次初始化，不改密码或 API 配置，不执行 `down -v`。具体管理命令见 [VPS](VPS-618HK.md) 与 [InstaBox](INSTABOX.md)。

本次是可向后兼容的加列迁移，回退到上一应用 `fce63e4` 可保留当前数据库：VPS 使用备份 `image` 中的旧镜像 ID 重标记为 `telegram-video-manager-app` 并 `up -d --no-build --force-recreate app`，再重启本项目 nginx；InstaBox 用旧 `IMAGE_TAG=fce63e486191` 执行 deploy。回滚前也先备份当前数据。旧版忽略新列和缓存，不以旧数据库覆盖新增账号/媒体。回退到更早账号结构版本仍需配套迁移说明。

Akile 3000、数据库、Komari、1Panel、外部 VPS 保活均不属于本项目变更范围。

## 检查记录

- Linux Docker：58 项测试通过，包含真实 H.264/AAC 原画分片、压缩视频数据哈希不变、A/V 相对起点差异小于 50ms、源文件哈希不变、缓存清理与磁盘保护；API 冒烟与依赖审计通过。
- 隔离无头 Chromium：真实 CDP 手机触摸、横滑、拖动中定位、最后目标、暂停/恢复、原画/流畅切换保留进度、缓冲不降级、320/390 触控尺寸通过。模拟 Telegram 多账号扫码/API/2FA 与退出失败重试仍通过；不向真实账号发送验证码或撤销授权。
- 部署后的公网与数据一致性结果将在实际完成后追加到本文。

测试音视频为合成媒体，时间戳检查不等同于对所有用户视频的人声口型主观验收；手机测试使用无头 Chromium，真机 Safari 仍待观察。

## 依据

[FFmpeg HLS 封装文档](https://ffmpeg.org/ffmpeg-formats.html#hls-2)、[HLS.js 1.7.3](https://github.com/video-dev/hls.js/releases/tag/v1.7.3)。第三方版本、校验与许可证在 `app/static/vendor/README.md`，所有脚本从本站加载。
