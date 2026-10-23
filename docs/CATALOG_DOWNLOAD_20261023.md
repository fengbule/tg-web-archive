# 频道挑选封面、下载标记与下载优化

本次改动针对“频道视频”挑选页，承接 [明暗主题、账号迁移与拖动预览](THEME_BACKUP_PREVIEW_20261023.md)。管理员密码、扫码/API 登录、账号授权和原画音视频播放保持原有设置。

## 使用

- 频道每页读取 24 条**视频消息**，跳过文字消息；向下滚动追加更早的视频，连续自动加载三页后点击“加载更多”继续。翻页保留勾选，底部提供返回顶部。
- 封面按可见范围加载，最多同时读取三张；失败显示“重试封面”，没有来源封面时明确提示。已下载视频优先使用服务器提取的本地封面。Telegram 原封面可能是片头黑帧，系统不会凭空补出尚未下载的视频画面。
- 视频卡片显示已下载、排队、下载进度、暂停和失败；已下载项直接“播放原画”，不重复勾选。下载完成后列表自动更新。
- 筛选“已下载 / 未下载”和文件名搜索作用于**已经加载**的视频；继续下滑可读取更多。批量加入队列后留在挑选页，暂停项可继续，失败项可重试；每次最多提交 100 项，剩余勾选保留。
- 下载到服务器完成后，在本地媒体库通过“下载原画”保存到手机/电脑，多个文件可打包 ZIP。Telegram 到服务器和服务器到本机是两段不同的网络链路。

## 下载策略

安装固定版本 `cryptg==0.6.0`，由 Telethon 使用原生加密实现。每个大文件默认最多三个 512KiB 并行请求，共用原账号客户端与连接；全局仍保留原来的两个下载 worker。未满 8MiB 的剩余数据使用顺序读取。遵循 [Telethon 下载接口](https://docs.telethon.dev/en/stable/modules/client.html#telethon.client.downloads.DownloadMethods.iter_download) 的 offset/stride/limit，不创建或复制第二份 Session。[Telethon 下载速度说明](https://docs.telethon.dev/en/stable/quick-references/faq.html#file-download-is-slow-or-sending-files-takes-too-long) 建议使用 cryptg，并提醒并发过高可能触发限流。

并行响应按原字节顺序写入 `.part`，内存只保留有限分片；分片长度异常会中断并保留连续前缀。暂停、取消和服务停止会先取消并等待未完成请求，再关闭读取器。原有任务和临时文件继续使用，完成前仍检查总长度并执行 ffprobe。

有 queued/downloading/pausing/retrying 任务时暂缓开始新的 480P 转码，优先完成下载；原画 faststart、HLS 和切片预览仍会准备。已经运行的转码不会被新下载强制中断，服务更新后未完成转码恢复排队。默认原画不变。

可选环境变量 `DOWNLOAD_PARTS` 范围 1–4，默认 3；设为 1 可退回顺序下载。一般先保持默认，出现 Telegram 限流时降低，不要无限增加并发。`DOWNLOAD_CONCURRENCY` 仍控制同时下载的文件数。新增变量直接由应用读取，无需改密码或重新登录。

## 数据与接口

无需数据库迁移。频道列表接口新增账号 ID、本地媒体 ID、本地封面可用性、任务状态及进度；实际文件存在才标记已下载。封面请求显式绑定账号，使用本地磁盘缓存、同一封面请求合并和 private 浏览器缓存；不会跨账号套用封面。

`POST /api/downloads` 可附 `account_id`，未提供时沿用当前账号，旧客户端兼容。网页提交时绑定打开频道时的账号，避免请求中途切换账号导致任务错属。

## 更新与管理

部署路径、备份、启动和回滚沿用 [上一版完整操作说明](THEME_BACKUP_PREVIEW_20261023.md#更新管理与回滚)。操作前确认主机、Compose 项目和挂载路径；只更新本项目容器，不删除卷、账号、`.part` 或源视频。

```bash
# InstaBox：8081；Akile 的 3000 端口不动
cd /data/workspace/tg-web-archive
bash scripts/instabox.sh backup
git fetch origin && git merge --ff-only origin/main
bash scripts/instabox.sh deploy
curl -fsS http://127.0.0.1:8081/health

# VPS：8080；先按上版文档备份 .env、数据库、Session 并保留旧镜像
cd /opt/telegram-video-manager
git fetch origin && git merge --ff-only origin/main
docker compose build app
docker compose up -d --no-deps --force-recreate app
docker compose up -d --wait --wait-timeout 180 app
docker compose restart nginx
curl -fsS http://127.0.0.1:8080/health
```

日常查看 `docker compose ps`、`docker compose logs --tail=80 app`；InstaBox 命令加 `-p tg-web-archive -f docker-compose.instabox.yml`。日志只在受保护环境查看，不上传真实配置或个人媒体信息。

回滚代码到本次更新前 `e1f37c0` 并重新构建本项目；InstaBox 执行 `bash scripts/instabox.sh deploy`。也可用备份记录的旧镜像恢复 app 容器。无需恢复旧数据库：恢复会丢失更新后新任务及进度。保留现有数据挂载及 `.env`，禁止 `down -v`。

凭据仍位于本机受保护目录 `D:/VibeCoding/Codex/20261020/output/tg-web-archive/`、桌面的 `C:/Users/fengbule/Desktop/618hk.txt` 和服务器原 `.env` / Session 数据目录；不提交到 GitHub。

## 验证

自动测试覆盖字节乱序响应后按序合并、任意断点续传、暂停关闭全部读取器、短分片拒收、视频过滤分页、真实本地文件检查、封面请求合并及下载优先于转码。无头浏览器覆盖封面加载/失败重试、无封面提示、已下载过滤、三页追加去重、选中项保留、批量恢复、完成后播放，以及明暗主题下 1440/390/320 像素宽度。

实机完成以下验证（应用版本 `3145387`）：

- 79 项 Python 测试、API 冒烟、依赖审计通过；账号、播放器、明暗主题/备份、频道目录四组无头浏览器检查通过。目录检查包含失败封面重试、下载完成状态刷新和批量恢复暂停项。
- VPS 公网真实频道首批返回 24 条视频，识别 2 条已下载；抽查 4 张 JPEG 封面及私有缓存/未登录拒绝访问，下滑追加到 48 条且无重复。手机 390/320 和桌面 1440 宽度无横向溢出，隐藏的手机侧栏不再向内容投下灰色阴影。
- 两台公网健康接口、账号授权和新版资源正常；容器内关键文件 SHA256 与提交一致，确认 Telethon 实际加载 cryptg。
- VPS 原画附件 Range 下载正常；InstaBox 用临时 20 秒音视频验证原画播放、Range 206/416、完整浏览器附件下载和 ZIP CRC，随后只删除该 UUID 测试媒体。
- 两台管理员密码、API 配置、Session auth key 指纹一致，SQLite quick_check 正常；VPS 30 个原有下载任务均在，更新前两个活动任务分别增加约 122MB 和 123MB，证明继续使用原断点。媒体记录未减少。Akile 容器及配置、两台 Komari 和 VPS 1Panel 保持原状态。

VPS 同一批活动任务的实际累计进度测速：更新前 20 秒约 **235,889 B/s**；更新后首次 20 秒约 **209,709 B/s**，稳定后 40 秒约 **249,030 B/s**。这些样本**没有证明显著提速**，不能用任务界面的瞬时速度相加代替累计进度测量。原生加密、有限并发和下载优先策略已经启用，但当前链路依然约 0.25MB/s。

排查时应用 CPU 约 0.5%、没有运行中的 ffmpeg，也未发现 FloodWait 或下载重试错误。文件连接 `149.154.175.60:443` 的 TCP RTT 约 237ms，并有乱序记录；账号主连接 RTT 约 39ms。独立下载 Cloudflare 5MB 样本约 16.5MB/s，但该近端线路不能代表 Telegram 的远端线路。剩余瓶颈更可能在远端文件连接或线路，现有证据不能区分服务器限速、账号限制或跨境网络质量，不应声称已经“满速”或靠继续增加并发即可解决。

本次更新前备份：

- InstaBox：`/data/workspace/tg-web-archive/backups/tg-web-archive-20261023T062417Z.tar.gz`。
- VPS：`/root/backups/tg-web-archive-20261023T062346Z-seek-upgrade/`，包含原 `.env`、数据库、Session/配置/封面归档及旧镜像记录；源视频留在原数据盘。

下载速度仍需观察不同源视频和时段；不要为了测速删除原任务、重置账号或复制同一 Session 到另一台机器同时连接。
