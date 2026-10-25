# 可选的非 AI 轻度增强版

媒体库的视频菜单和播放器新增“生成轻度增强版”。用户明确请求后后台生成，完成后手动播放或另存到手机/电脑。默认继续使用原画，生成完成不会自动切换，重新打开及切换下一集也默认原画。播放器顶部画质键按“原画 → 已生成的轻度增强 → 已生成的 480P 流畅 → 原画”循环；底部增强按钮可直接比较原画和增强版，保留位置、暂停状态和倍速。

## 处理与限制

没有 AI 模型、外部增强 API 或新增 Python 依赖。`app/enhancement.py` 的 `clean-sharp-v1` 使用 FFmpeg 弱去块、轻度时空降噪和亮度锐化：

```text
deblock=filter=weak:block=8:alpha=0.025:beta=0.015:gamma=0.015:delta=0.015,
hqdn3d=0.6:0.5:1.0:0.8,
unsharp=5:5:0.45:5:5:0,
pad=ceil(iw/2)*2:ceil(ih/2)*2
```

不统一拉高亮度/饱和度，不放大到虚假的 4K。原始分辨率保留，奇数尺寸最多补齐一像素，旋转视频按显示方向处理。H.264 CRF 17、fast 预设，保留源帧率/可变帧率，每两秒强制关键帧，MP4 faststart；增强文件仍支持 Nginx 加速、HTTP Range 和附件下载。AAC/MP3/ALAC 原音轨复制，其他音轨转换为 AAC 192k；音视频处于同一文件和播放时钟。输出发布前检查尺寸、已知帧数、时长、音轨和 A/V 起始偏移；当前不处理 PQ/HLG HDR，失败时明确保留原画。

滤镜能改变边缘观感、降低部分噪声，无法保证恢复真实细节。受控照片平移/模糊/压缩样片比较了 0.25、0.45、0.75 锐化及 CAS；强锐化带来更多偏差，因此保留温和的 0.45。该样本相对干净参考的 SSIM：原压缩输入 0.961527、0.45 配方 0.959826、0.75 配方 0.957010。这里没有把主观锐度提高宣传成客观信息增加；不同来源建议对比后选择。测试照片来自 [scikit-image 的公共领域 NASA 样例](https://scikit-image.org/docs/stable/api/skimage.data.html#skimage.data.astronaut)，样片不提交仓库。算法参数见 [FFmpeg 滤镜文档](https://ffmpeg.org/ffmpeg-filters.html)。

## 任务、数据和管理

增强文件为原文件旁的 `*.enhanced.mp4`，中间文件为 `*.enhanced.tmp.mp4`。SQLite 仅增补 `media.enhanced_*` 六个字段；源视频、原图、账号、密码和 Session 不替换。重命名视频同步跟踪增强文件；删除单独增强版保留原画，删除整条媒体才清理各版本。

单 worker 串行处理，FFmpeg 限制两条编码/解码线程、一条滤镜线程，Linux 使用 nice 10。先处理原画索引/分片/预览，再做可选转码；有排队或活动下载时增强等待，生成中出现下载会终止临时编码，下载空闲后从头重新生成。关闭网页不停止任务；服务重启将 processing 退回 queued。生成进度来自 FFmpeg 已输出时间，无伪造进度。取消会终止进程并清理中间文件；失败可重试。空间估计和持续磁盘保护线至少预留 2 GiB，失败不会覆盖原视频。

以下请求均要求现有管理员会话；不要在终端输出真实 Cookie：

```bash
# COOKIE_JAR 指向管理员已登录并安全保存的本机会话文件；MID 为媒体 ID。
curl -fsS -b "$COOKIE_JAR" "$BASE/api/media/$MID/enhanced"
curl -fsS -b "$COOKIE_JAR" -X POST "$BASE/api/media/$MID/enhanced"
# 取消排队/处理任务，或仅移除已生成增强版：
curl -fsS -b "$COOKIE_JAR" -X DELETE "$BASE/api/media/$MID/enhanced"
# 下载增强版（支持 Range）；quality=original 始终读取原画。
curl -f -b "$COOKIE_JAR" "$BASE/api/media/$MID/stream?quality=enhanced&download=true" -o enhanced.mp4
```

## 双机部署与回滚

部署前确认主机、磁盘、容器和端口，备份 SQLite、全部账号 Session、加密配置和 `.env` 并保存旧镜像。保留现有 Akile/3000、Komari、1Panel、birth、8084 中转及外部保活配置。真实凭据、数据和日志不能提交 Git。

本轮部署前源码 `acc0958`、应用 `a5fe34b`，备份及回滚标签：

- VPS `/root/backups/tg-web-archive-enhancement-20261025T135249Z`，镜像 `tg-web-archive-vps-rollback:enhancement-20261025`。
- InstaBox `/data/workspace/tg-web-archive/backups/tg-web-archive-enhancement-20261025T135434Z`，镜像 `tg-web-archive-app:rollback-enhancement-20261025`。

VPS 在 `/opt/telegram-video-manager` 拉取确认后的版本，`docker compose -p telegram-video-manager build app`，随后 `up -d --no-deps --force-recreate --wait app`，只重启本项目 nginx。公网端口仍为 8080。

InstaBox 机器 `m_agqv47q5at4mzg6nr336pvg33u`，目录 `/data/workspace/tg-web-archive`。拉取代码，**只更新 `.env` 的 IMAGE_TAG** 为应用提交短 SHA；使用 `docker compose -f docker-compose.instabox.yml -p tg-web-archive` 执行同样的 build/up/restart nginx，回环端口继续为 8081。不重新初始化账号或配置，不修改密码。

回滚源码到 `acc0958`。VPS 将保存镜像标记回 `telegram-video-manager-app`，InstaBox 将 IMAGE_TAG 设为 `rollback-enhancement-20261025`；分别 `up -d --no-deps --no-build --force-recreate --wait app`，只重启自己的 nginx。新增数据库字段与旧版本兼容，通常无需恢复数据库，更不能用旧备份覆盖期间的新下载/账号。仅在明确需要完整灾难恢复时停止本项目 app 后恢复对应备份。禁止 `down -v`、删除 data 或覆盖现有 Session。

## 验证

`tests/test_enhancement.py` 运行真实 FFmpeg，检查源文件 SHA 不变、原音轨码流一致、帧数/尺寸/时长、两秒关键帧、旋转/可变帧率及音轨转换、磁盘不足、取消、下载优先与重启恢复。独立 `enhancement_api_smoke.py` 使用临时数据验证匿名拒绝、幂等生成、取消、Range、附件命名、重命名和单独移除。

`enhancement_ui.mjs` 用真实混合 A/V 样片验证完整后台生成、默认原画、手动切换保留暂停/位置、快进、本机下载、取消入口以及 320/390/1440 宽度的明暗布局。继续运行原画播放、画面点击、方向锁/选集和相册封面回归。桌面及手机尺寸截图须实际查看；不把仿真浏览器当作实机 iPhone 验收。
