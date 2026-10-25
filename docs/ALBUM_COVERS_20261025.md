# 修正 TG 相册原封面

前两轮确认了视频文档缩略图来自 Telegram，但这不能证明图片与 TG 帖子展示的原封面一致。本轮直接读取真实 TG 消息关联，发现 VPS 可访问的 61 个已下载视频均有 `grouped_id`，每个相册包含一张独立照片；这些视频本身没有 `video_cover`。前两轮取的是约 1 KB 的视频文档缩略图，而用户看到的是同相册约 100 KB 的独立图片。三组独立下载的照片与文档缩略图已留在受保护目录作对照，不提交真实图片、消息内容或会话到仓库。

## 当前取图与缓存

优先级现在为：视频明确指定的 `video_cover` → **同频道、相同 grouped_id 的相册首张照片** → 最大静态文档缩略图 → 已有本地图。只在原消息前后各 10 个消息 ID 内读取相册候选，严格验证相册 ID；附近其他相册或没有相册关联的照片不会被绑定。多图相册用消息 ID 最小的照片作代表；不获取整个视频、不加入任何频道、不改 TG 消息。Telegram 的关联语义见 [message.grouped_id](https://core.telegram.org/constructor/message) 和 [媒体相册](https://core.telegram.org/api/files)。

新缓存 `thumbnails/telegram/source-v3/<账号>/<频道>/<视频消息>.jpg` 不复用此前 `source-v2` 的文档缩略图。`.source` 新增 `telegram-album`，`.json` 记录源照片消息 ID、相册 ID 和来源类型，便于逐条审计。只有取得有效 JPEG 才更新 `media.thumb_path`，保留旧图片与原视频。已有后台“同步 TG 封面”会对所有已下载视频应用此规则，普通请求也支持新缓存按需生成。

前端封面 URL 更新到 `v=4`，避免旧的 1 小时浏览器缓存。此后接口返回 `Cache-Control: private, no-cache`、基于文件纳秒修改时间/大小的 ETag 和 `Vary: Cookie`。浏览器每次使用前核对版本，图片未变返回 304；同步替换后 ETag 改变，同一个 URL 返回新图片。鉴权在条件缓存判断之前，陌生浏览器带上别人的 ETag 也只能得到 401。

## 测试和验收方法

- `test_album_cover.py` 验证旧文档缓存替换、相册严格关联、邻近其他相册排除、自定义视频封面优先、原视频与旧图保留。
- `album_cover_ui.mjs` 使用独立相册照片，验证频道与新下载媒体库图片一致；在同一个浏览器里更换测试相册图并同步，确认实际画布像素从旧图变为新图，验证 ETag/304、匿名 401 与播放器海报。
- 继续运行标题、收藏、频道、设备模式和播放器各项回归。
- 真实验收需把新缓存 `.json` 中的照片消息 ID 与本次独立 TG 审计结果逐条核对，并将三个公网封面响应与独立下载的同相册照片比较字节。仅比较两个本项目接口，或只看 `X-Thumbnail-Source`，不足以证明图片正确。

## 更新和回滚

延用 [双实例部署步骤](CLIENT_VIEWS_20261025.md) 及 [后台封面同步接口](BUFFER_COVER_AUTH_20261025.md)。先备份数据库、Session、配置、全部缩略图并保存回滚镜像；分别只重建本项目 app、重启自己的 nginx，健康通过后执行后台封面同步，检查分类计数和源图片证据。

本轮更新前仓库 `e18e181`，应用 `76c0210`。备份为：

- VPS `/root/backups/tg-web-archive-original-cover-20261025T114900Z`，镜像 `tg-web-archive-vps-rollback:original-cover-20261025`。
- InstaBox `/data/workspace/tg-web-archive/backups/tg-web-archive-original-cover-20261025T114857Z`，镜像 `tg-web-archive-app:rollback-original-cover-20261025`。

回滚源码到 `e18e181`，VPS 将回滚镜像标记为 `telegram-video-manager-app`，InstaBox 设 `IMAGE_TAG=rollback-original-cover-20261025`；各自 Compose `up -d --no-deps --no-build --force-recreate --wait app` 后重启自己的 nginx 并检查健康。新图片和 `thumb_path` 与旧应用兼容，无需恢复数据库。禁止删除媒体、账号、Session、新旧封面或执行 `down -v`。

原密码、账号和数据保持不变。VPS 另 1 个来源在本轮真实读取中返回 `ChannelPrivateError`，无法取得 TG 原图时保留其本地图，不把失败计作原封面已更新。

## 上线结果

双机应用已更新到 `a5fe34bb21d1`，构建、健康及运行代码/资源校验通过。46 项 Python、两组 API 冒烟、九组无头浏览器回归通过，手机尺寸隔离截图已目检。

VPS 首次后台任务更新 55 张、沿用 6 张旧 TG 图；对这 6 张逐条重试后，**61 个可访问视频全部改用 `telegram-album` 原图**。新缓存记录的源照片消息 ID 逐条匹配独立读取的相册消息。三张新缓存与独立从 TG 下载的相册照片精确字节一致，且都不同于旧文档缩略图；手机尺寸公网无头浏览器实际加载的这三张图片，响应字节及原始尺寸也与独立照片一致。验收包含实际浏览器显示资源，没有仅凭两个项目接口相同就认定图片正确。

另外 1 个无权限来源保留本地图；原 62 个视频文件路径/大小、下载记录、发送记录、4 条收藏、原授权账号、密码/API/Session 密钥指纹保持一致，SQLite 检查通过。InstaBox 原生实例媒体库为空，已更新代码并验证空状态，未声称其真实媒体播放已验证。

公网原画播放、另存附件 Range、频道浏览和视图保持通过；三个入口全新无痕浏览器均需原后台密码，敏感接口和伪造 Cookie 被拒绝。VPS 封面条件 GET 返回 304；HTTPS 中转原有 `no-store` 策略更严格，未修改中转配置。Akile、Komari、1Panel、birth 和保活均保持原状，一次性测试容器已移除，验证 Cookie 从私有快照清除。
