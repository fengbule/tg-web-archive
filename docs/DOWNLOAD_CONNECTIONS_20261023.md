# 下载慢的定位与文件连接池

后续进一步比较请求、连接、分片与网络策略，见 [第二轮下载调优](NETWORK_TUNING_20261023.md)。本文保留第一轮的默认四连接方案与当时测量，新默认值以第二轮文档为准。

本次针对 VPS `84.54.3.25:8080` 的 **Telegram → 服务器**下载做受控测试。网页保存到手机/电脑是另一段传输链路。本次不改管理员密码、API 配置、账号授权、已有视频或任务，也不需要重新扫码。

## 实测原因

暂停原有可运行队列，保留 `.part`，短暂停止本项目 app，独占原 Session 读取同一视频前 8 MiB；测试结束自动恢复队列与 app。没有让两个客户端同时打开同一 Session。

| 读取方式 | 实际吞吐（B/s） | 用时 |
| --- | ---: | ---: |
| 单请求、单文件 TCP | 218,101 | 38.462 s |
| 三路请求、共用同一文件 TCP | 222,642 | 37.678 s |
| 三路请求、三条独立文件 TCP | 599,062 | 14.003 s |

三次都是 8,388,608 字节且 SHA256 一致。Telethon 1.45.0 原生为每个目标 DC 缓存一条 exported sender，所以增加分片/任务数仍共用同一条慢连接。本机账号主 DC 为 5，样本文件 DC 为 1；实测 RTT 约 39ms / 237ms，CPU 空闲、没有同时运行 FFmpeg，也未发现 FloodWait。**已确认共享文件 TCP 是吞吐瓶颈；未证实运营商或 Telegram 的具体限速策略**，不把原因归结为账号等级。

连接池实现复测，8 MiB 冷启动含建连约 402,289 B/s，复用连接约 633,737 B/s；两个任务共用三条文件连接，合计 664,148 B/s。读取结果与磁盘已有 `.part` 对应范围逐字节哈希一致，所有借用均归还。原先共用连接的优化记录保留在 [上版交接](CATALOG_DOWNLOAD_20261023.md)，此次实验补充了之前未定位的瓶颈。

## 实现与限制

- `app/download_connections.py` 给原 Telethon 客户端提供有上限、可复用的跨 DC 文件连接池。同账号的多个下载共享额度；每个文件仍按顺序落盘。
- 每条额外连接生成独立的内存 auth key，使用 Telegram 的 [exportAuthorization](https://core.telegram.org/method/auth.exportAuthorization) / [importAuthorization](https://core.telegram.org/method/auth.importAuthorization) 跨 DC 授权；不克隆、不导出登录 Session 文件或主 auth key。初始化请求使用副本，不修改主客户端正在使用的请求。
- 使用原生 Telethon 下载迭代器，保留 RPC 错误、迁移和限流处理。文件与账号同 DC 时走原生主连接；池满且请求其他 DC 时走原生共享连接，避免另一个任务等待整部电影完成。
- 暂停、错误、迁移和取消都归还读取器的连接借用；空闲约 30 秒后关闭文件连接。结束账号会话、断开账号及应用停止会关闭对应池，其他账号不受影响。
- 任意断点先补齐一个 512KiB 块，再从对齐位置继续，避免后续每片重复读取重叠块。只追加未保存的字节；总长校验、ffprobe、原子移动及原画音视频后处理保持原流程。
- 使用 Telethon 私有接口，依赖固定 `telethon==1.45.0`。升级 Telethon 时必须跑原生迭代器集成测试和真实小样本对照，不能只检查能否 import。

同一后续时段的连接数对照：三连接复用 320,555 B/s、四连接复用 489,093 B/s；四连接双任务合计 408,787 B/s，所有样本与原断点哈希一致。不同轮次速度有明显波动，不把四连接宣称为保证带宽。

`DOWNLOAD_PARTS` 控制每文件并行请求数；`DOWNLOAD_CONNECTIONS` 控制每账号额外跨 DC 文件连接上限，两者范围均为 1–4，**应用默认均为 4**，依据同轮复用样本选择。`DOWNLOAD_CONCURRENCY` 仍控制任务数，保持原有 2。连接数不会按文件数倍增，也不无限开连接。

设 `DOWNLOAD_CONNECTIONS=1` 可关闭专用连接池，退回原生共享文件连接；再设 `DOWNLOAD_PARTS=1` 可退回顺序读取。不要更改密码或删 Session 来调整下载参数。已有低于 8MiB 的尾部继续使用原生顺序下载。网络路径、目标 DC 与 Telegram 策略会变化，样本增益不保证适用于每个文件。

## 更新、管理与回滚

先确认主机、Compose 项目、挂载及端口。仅操作本项目；禁止 `down -v`、删除 `.part`、恢复过时数据库来回滚代码。

InstaBox 使用独立项目 `tg-web-archive`、目录 `/data/workspace/tg-web-archive`、端口 8081，保留 Akile 3000、Komari 和保活：

```bash
cd /data/workspace/tg-web-archive
bash scripts/instabox.sh backup
git fetch origin && git merge --ff-only origin/main
bash scripts/instabox.sh deploy
docker compose -p tg-web-archive -f docker-compose.instabox.yml ps
curl -fsS http://127.0.0.1:8081/health
```

VPS 项目 `telegram-video-manager`、目录 `/opt/telegram-video-manager`、端口 8080：更新前保存原镜像 ID/回滚标签与 commit，短暂停 app，用 SQLite backup 保存数据库，并在 root 私有备份目录保存 `.env`、Session 和配置；保留下载目录。启动失败也要恢复原 app。

```bash
cd /opt/telegram-video-manager
# 先按上述要求备份，私有备份权限 700/600
git fetch origin && git merge --ff-only origin/main
docker compose build app
docker compose up -d --no-deps --force-recreate app
docker compose up -d --wait --wait-timeout 180 app
docker compose restart nginx
curl -fsS http://127.0.0.1:8080/health
docker compose ps
```

两份现有 Compose 均通过 `env_file: .env` 传入参数；未设置新增变量时使用应用默认值。调整后重新创建 app。容器内 `os.getenv` **只检查这三个下载参数**，不要打印整个环境。

日常查看本项目 `docker compose logs --tail=80 app`；日志留在受保护环境。衡量速度时比较至少 40 秒内全部任务的累计 `downloaded_bytes` 增量，包含期间刚完成的任务，勿把某个瞬间的速度读数当作持续吞吐。

回滚使用更新前的 `3145387` 应用代码重新构建，或使用备份记录的旧镜像重建 app；保留现有 `.env` 与数据挂载，重新启动 app/nginx。无需恢复数据库，不丢弃更新后的进度。本机受保护交接目录和服务器备份记录保存实际镜像、提交与备份路径；真实配置、Session、数据库、日志均不提交到 GitHub。

## 验证

测试覆盖原生 Telethon 迭代器、多个任务共享连接上限、乱序响应按序写入、非对齐断点的精确内容、暂停与续传、迁移/其他 DC 回退、初始化取消、空闲回收、退出账号与应用关闭。生产发布还需核对：镜像内源码哈希、cryptg 实际启用、账号与 auth key 指纹、原任务/断点进度非递减、SQLite quick_check、公网健康以及原有其他服务未变。

## 本次双实例发布结果

应用提交 `aa56d25798ca414a2a89074c1801b45588e8bc5c` 已构建并运行在 VPS 和 InstaBox；文档后续提交无需重建镜像。

- Linux 上 **94 项测试、API 冒烟、依赖审计通过**。两机容器内关键源码 SHA256 与该提交一致，确认 Telethon 使用 cryptg。
- VPS 新版启动预热后，原有两个活动任务的全部进度在 **40 秒**内合计增加约 20.97MB，实际 **524,275 B/s**。上一版 40 秒样本为 249,030 B/s，约 **2.1 倍**。这是两个时段的真实生产样本，非保证带宽；比单连接对照也有明显改善。样本阶段 CPU 约 1%，未见下载异常、FloodWait 或并发 FFmpeg。
- 原有 **30 个下载记录**全部保留，任务 ID、账号、频道与消息关联一致，断点进度非递减。更新前已完成的任务保持完成，原可运行队列已恢复。账号、API/管理员密码配置、Session auth key 指纹及 SQLite 完整性检查均通过。
- 两机公网健康、未登录拒绝媒体访问和授权账号正常。VPS 无头浏览器确认首批 24 条视频、3 个已下载标记、4 张真实 JPEG 封面、追加至 48 条无重复；明暗主题下手机 390/320 与桌面 1440 宽度无溢出，原画附件 Range 206 正常。
- Akile 容器 ID、配置与 3000 健康接口保持一致；两机 Komari 与 VPS 1Panel 未重启，外部保活未改。

本次更新前备份：

- InstaBox：`/data/workspace/tg-web-archive/backups/tg-web-archive-20261023T072646Z.tar.gz`。
- VPS：`/root/backups/tg-web-archive-20261023T082017Z-seek-upgrade/`；其中有更新前提交、镜像 ID、私有配置/Session/数据库备份。原画与 `.part` 在原挂载位置保留。
- 受控测速、验证快照及私有交接：本机 `D:/VibeCoding/Codex/20261020/output/tg-web-archive/`，保持原 ACL 保护；InstaBox 连接与登录文件仍在该目录，VPS SSH 凭据仍在桌面的原 `618hk.txt`。不把凭据内容、数据或日志提交到仓库。

访问地址：[VPS](http://84.54.3.25:8080)、[InstaBox](https://8081-agqv47q5at4mzg6nr336pvg33u.instabox.tech)。后续观察不同 DC/时段的持续吞吐和下载自动重试；如触发限流，降低下载连接/分片数，保留现有断点。
