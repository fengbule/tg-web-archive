# 定位加载进度、原封面同步与访问保护

拖动进度条、横滑定位和快进后，画面底部显示加载百分比及小进度条。HLS 使用**当前目标片段**的 `stats.loaded / stats.total`，片段接收完成但尚未解码时明确显示“片段已接收 · 正在解码”。原生播放器使用目标位置起最多 3 秒的连续 `video.buffered` 时长，标注已缓冲秒数；可播放事件到达后显示就绪并收起。百分比衡量本次定位所需的片段/缓冲，不是整个视频下载进度。新定位排除旧片段，切换集数/画质及关闭播放器会清理监听和定时器。没有新数据时数值不凭时间增加，弱网停住时不会假装已完成。依赖依据：[HLS LoaderStats](https://hlsjs.video-dev.org/api-docs/hls.js.loaderstats)、[浏览器媒体 progress 事件](https://developer.mozilla.org/en-US/docs/Web/API/HTMLMediaElement/progress_event)。

不增加第二个音视频播放器，不改变原画优先、音画同轨、拖动预览图、暂停/方向锁/选集行为，也不额外请求完整视频来统计字节。原生 Safari 的缓冲更新粒度由浏览器决定，百分比可能跳变；真实 iOS/Android 长时使用仍需观察。

## 已下载视频封面

媒体库工具栏新增“同步 TG 封面”。它在后台依次重读每条最新 TG 消息，绕过旧消息对象、旧图片和失败退避缓存，按自定义 `video_cover` → 最大静态文档缩略图 → 既有图片的顺序同步。每次只运行一个全库同步任务，两条间隔 0.2 秒；接口返回当前进度，以及新下载、沿用旧 TG 图、本地图回退、不可用的独立计数。进程关闭时取消任务，下次手动重试即可。

成功获取的 TG 图直接更新 `media.thumb_path`，让**已经下载的媒体、收藏、选集和播放器海报**也使用同一张原图。视频文件、原文件名、账号与下载记录不变；旧抽帧图保留，TG 获取失败时不覆盖已有图片。日常请求对超过一天的缓存重读 TG 消息；前端 `v=3` 避开上轮浏览器封面缓存。无法访问原消息或 TG 未提供图片时，会明确计入沿用/回退/不可用，不保证每条都有原图，不把邻近图片猜测绑定到视频。

管理接口均要求现有管理员会话：

```text
POST /api/media/covers/refresh   启动或返回正在执行的同一个任务
GET  /api/media/covers/refresh   查询 status、done、total 和分类计数
```

通过网页执行最方便。运维脚本应在服务器进程中读取已授权配置并生成短期验证会话，在内存中请求本机接口；不要把 Cookie 放在命令行、终端输出或 Git 中。不要直接修改 Session、密码或清空数据目录。

## 陌生浏览器验证

三个公开入口分别用全新的 Chromium 无痕上下文验证，未导入任何旧 Cookie、localStorage 或浏览器配置。首页可以加载登录界面的公开 HTML，但不能显示媒体库。媒体、原画流、另存下载、封面、HLS、预览、账号、收藏、任务和安全设置接口均要求管理员登录；伪造 `tvm_session` 不能通过，`/protected-media/` 无法从外部直接访问。现有密码未修改。验证程序只读取接口，不尝试猜测密码。

公网使用现有 HTTPS 中转入口也会要求同一 VPS 后台密码：

- VPS：<http://84.54.3.25:8080>
- VPS 的 HTTPS 中转：<https://8084-agqv47q5at4mzg6nr336pvg33u.instabox.tech>
- InstaBox 独立实例：<https://8081-agqv47q5at4mzg6nr336pvg33u.instabox.tech>

## 更新、验证与回滚

更新流程沿用 [双实例管理文档](CLIENT_VIEWS_20261025.md)。更新前创建数据库一致性快照、Session/配置与 thumbnails 备份并保留旧镜像；分别只重建本项目 app、重启自己的 nginx，其他容器、Komari 和保活保持原状。后台构建、健康通过后再执行全库封面同步，检查逐项统计及实际图片、已有数据和陌生浏览器保护。

当前轮次更新前仓库 `461ee54`、运行应用 `7ca8165`。备份：

- VPS：`/root/backups/tg-web-archive-buffer-cover-20261025T111914Z`；镜像 `tg-web-archive-vps-rollback:buffer-cover-20261025`。
- InstaBox：`/data/workspace/tg-web-archive/backups/tg-web-archive-buffer-cover-20261025T111910Z`；镜像 `tg-web-archive-app:rollback-buffer-cover-20261025`。

回滚代码到 `461ee54`，VPS 把回滚镜像标为 `telegram-video-manager-app`，InstaBox 使用 `IMAGE_TAG=rollback-buffer-cover-20261025`；各自 Compose `up -d --no-deps --no-build --force-recreate --wait app` 后重启自己的 nginx，检查健康即可。新封面仍兼容旧代码，无需恢复数据库；不要 `down -v` 或删除账号、原媒体、新旧封面。

测试入口：`tests/test_catalog.py`（强制刷新、过期重新读取、旧图回退与本地引用更新）、`tests/test_cover_refresh.py`（单任务、部分失败及取消）、`tests/buffer_cover_auth_ui.mjs`（无登录访问拒绝、30→47% 实际统计模型、没有数据不增长、跳转重置、原生缓冲、真实限速 HLS 与暂停定位、下载视频封面同步）。同时运行现有封面/标题、视图、频道、收藏和各播放器回归。隔离测试数据不可挂载生产卷。

上线前 43 项 Python、两组 API 冒烟、八组无头浏览器回归通过。最后修正后台预取先开始、之后才发生 waiting 的统计遗漏，再复测新功能与原画播放器通过；实际限速 HLS 捕获到 1%–25% 连续变化，片段尚未收完时已经可以渐进播放，所以就绪后立即收起，不阻塞到全片段下载完成。30%→47%、原生 30%/50%、新跳转清零、旧片段排除、预取后卡顿等边界在可控统计测试中验证。手机宽度截图已目检。
