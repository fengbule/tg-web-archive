# 频道挑选封面、下载标记与下载加速

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

实机部署与测速结果在完成验证后补充。下载速度受 Telegram 数据中心、账号限制、源文件及 VPS 网络影响，不能保证每条视频或每个时段相同。
