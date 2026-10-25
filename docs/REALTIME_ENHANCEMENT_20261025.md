# 在线实时增强：边看边处理，不另存视频

播放器右下角的“增强”按钮或底部“选择实时增强”打开设置，支持关闭、自然、清晰、较强。推荐先试自然；按住“看原画”可临时比较，松手恢复，播放和声音继续。选项保存在当前浏览器，下次打开视频仍使用所选强度；新浏览器默认关闭。媒体菜单也有“实时增强 · 不另存视频”快捷入口。

增强由当前手机/电脑的 WebGL 处理正在播放的画面，没有 AI 模型、服务器实时转码或额外增强视频文件。原画仍是默认播放源，下载得到所选源文件，不包含屏幕增强。原有正常播放分片/缓存不受此选项改变。已生成的离线增强文件保留；只有明确需要可下载的处理文件时，才展开“离线增强 · 另存一份，占用存储”。

## 实现与限制

- `realtime-enhancement.js`：对当前帧做五点亮度高通，平坦低对比区域用噪声门限抑制，限制亮度增量和局部超调；三个强度为 0.22 / 0.45 / 0.70。不会改饱和度、放大原始分辨率或还原丢失的细节，较强档可能凸显噪点。
- 保持原有唯一 `<video>` 和音轨，视频帧上传纹理后显示到覆盖画布，不另建音频、另启播放器或更换源。优先用 `requestVideoFrameCallback` 跟随帧；旧浏览器退回 `requestAnimationFrame`，暂停时只重绘一次，后台页停止处理。
- 拖动/更换片源时先显露原视频，拿到新帧后再增强。画布不接收点击/触摸，不影响拖动、锁屏、横屏和只按暂停键暂停。播放控件保持在画面下方。
- 不支持 WebGL、纹理超限、上下文丢失或连续处理开销过大时恢复原画并显示原因。系统原生视频全屏及画中画显示原画，返回网页播放器后恢复；网页内全屏仍可增强。
- 额外消耗客户端 GPU、纹理内存和电量，实际性能取决于设备与浏览器。帧回调与浏览器合成并非严格实时，不能承诺所有设备零延迟或所有素材都有主观改善。

浏览器实现依据：[MDN 视频帧回调](https://developer.mozilla.org/en-US/docs/Web/API/HTMLVideoElement/requestVideoFrameCallback)、[WebGL 视频纹理](https://developer.mozilla.org/en-US/docs/Web/API/WebGLRenderingContext/texImage2D)。

## 运维与交接

此版本只改静态界面和浏览器测试，无新依赖、服务、端口、数据库字段或配置项。上线前备份现有配置及 SQLite/Session，并保留旧镜像。VPS 继续用原 8080 入口，InstaBox 保持独立 Compose 项目及 8081，8084 中转和其他应用均不由本次操作管理。

```sh
# VPS
cd /opt/telegram-video-manager
git fetch origin && git merge --ff-only origin/main
docker compose -p telegram-video-manager build app
docker compose -p telegram-video-manager up -d --no-deps --force-recreate --wait app
docker compose -p telegram-video-manager restart nginx
curl -fsS http://127.0.0.1:8080/health

# InstaBox：替换为本次待发布代码的 12 位提交号；更新 .env 的 IMAGE_TAG 时保留其余内容
cd /data/workspace/tg-web-archive
git fetch origin && git merge --ff-only origin/main
export IMAGE_TAG="$(git rev-parse --short=12 HEAD)"
docker compose -p tg-web-archive -f docker-compose.instabox.yml build app
docker compose -p tg-web-archive -f docker-compose.instabox.yml up -d --no-deps --force-recreate --wait app
docker compose -p tg-web-archive -f docker-compose.instabox.yml restart nginx
curl -fsS http://127.0.0.1:8081/health
```

静态资源使用新 URL 版本号。网页未出现“增强”时重新加载；临时关闭可直接选择“关闭”，或删除当前浏览器 `localStorage['tvm-realtime-enhancement-v1']` 后重开播放器。不要清空 Session 或删除媒体。

本次升级前的受保护备份及回滚镜像：

- VPS：`/root/backups/tg-web-archive-realtime-20261025T155631Z`，`tg-web-archive-vps-rollback:realtime-20261025`。
- InstaBox：`/data/workspace/tg-web-archive/backups/tg-web-archive-realtime-20261025T155625Z`，`tg-web-archive-app:rollback-realtime-20261025`。

回滚时源码切回 `d1015ad`；VPS 将回滚镜像标记为 `telegram-video-manager-app`，InstaBox 的 IMAGE_TAG 设为 `rollback-realtime-20261025`。分别使用本项目的 `up -d --no-deps --no-build --force-recreate --wait app` 并重启自己的 nginx。没有数据迁移，正常回滚无需恢复旧数据库，避免覆盖升级期间的新下载/账号。禁止 `down -v` 或删除 data。

## 验证方法

`tests/realtime_enhancement_ui.mjs` 配合独立 `tests/accounts_ui_server.py`、合成音视频运行：实际读取 GPU 画布像素与同一原始帧比较，验证增强确有作用、方向正确、唯一播放时钟与暂停/进度不变、对比、连续跳转、全屏、偏好、上下文丢失、无 WebGL 及旧回调降级。检查 320/390/1440 宽度、明暗主题和 44px 触摸区域；确认没有提交生成增强副本的请求。

测试服务只绑定回环测试端口，不连接真实 Telegram，不写生产数据库；截图使用合成内容。真实 iPhone/Safari 硬件性能仍须日常观察，模拟系统全屏通知不等于完整真机验收。

独立 Linux 容器内 140 项 Python 测试和 3 组 API 冒烟检查通过；6 组无头浏览器检查通过：实时增强、离线增强、播放/拖动、控件、锁屏/选集、TG 相册封面。640×360 同帧像素比较中，45,047 个色彩通道变化超过 1/255，平均变化约 0.304/255，确认实际处理且画面方向正确；这只是算法工作校验，不是主观画质评分。键盘按住对比不触发全局暂停快捷键，320/390/1440 明暗主题截图已目检，较强模式不会自动创建后台增强任务。
