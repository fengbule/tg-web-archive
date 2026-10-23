# 第二轮下载与网络对照

承接 [第一轮文件连接池](DOWNLOAD_CONNECTIONS_20261023.md)。目标为 VPS `84.54.3.25:8080` 的 Telegram → 服务器下载；保留账号、管理员密码、原视频、任务和断点。服务器 → 手机/电脑附件下载是另一段链路。

## 基线与方法

前一版生产双任务在 40 秒内合计 524,275 B/s；本轮开始时再测 40 秒为 **524,280 B/s**，基线可复现。测试期间仅暂停原可运行队列，停止本项目 app 来独占原 Session；不并开原 Session、不删除 `.part`。每轮由退出 trap 恢复原队列和健康 app。

专用进程用同一个文件的前 16 MiB、相同原账号、相同 DC 比较，使用原生 Telethon 迭代器；每个结果核对本地已有断点的 SHA256，并确认连接借用全部归还。实验提高的上限只存在于诊断进程中；选定配置和资源上限另行纳入应用。

## 第一组：请求、连接与分片

以下是专用进程的**单文件**样本，不直接当成网页双任务的持续速度：

| TCP 数 | 并行请求数 | 分片 KiB | 实测 B/s |
| ---: | ---: | ---: | ---: |
| 4 | 4 | 512 | 305,835 |
| 4 | 8 | 512 | 326,760 |
| 4 | 16 | 512 | 323,669 |
| 4 | 8 | 1024 | 309,120 |
| 4 | 16 | 1024 | 320,574 |
| 8 | 8 | 512 | 645,633 |
| 8 | 16 | 512 | 661,659 |
| 8 | 16 | 1024 | 654,883 |
| 12 | 12 | 512 | 519,214 |
| 12 | 24 | 512 | 522,205 |
| 4（末尾复测） | 4 | 512 | 321,941 |

八条连接有明确收益；同样连接数增加请求或分片大小没有额外明显收益，十二条连接反而回落。因此保留 512 KiB，应用默认每文件 **8 个请求**、每账号 **8 条额外跨 DC 文件连接**，继续保留原 **2 个下载 worker**。两个任务共用这八条连接。

应用参数：`DOWNLOAD_PARTS=8`（允许 1–16）、`DOWNLOAD_CONNECTIONS=8`（允许 1–16）。硬上限防止误填参数造成无界请求/连接；8 MiB 以下尾部继续顺序读取。16 个 512 KiB 分片的读取窗口有界，暂停、错误、迁移、重启与账号退出仍释放原生读取器及连接。连接初始化和空闲重建有额外耗时，优先复用整个队列的连接。

Telegram [下载规范](https://core.telegram.org/api/files) 要求按合法 offset/limit 分块；1 MiB 对照也遵守块边界，但无明显收益，因此不修改 Telethon 全局分片常量。固定依赖仍为 Telethon 1.45.0 / cryptg 0.6.0。

## 网络检查

VPS 主机与应用网络命名空间原本均使用 BBR、接收自动调节、窗口扩展和 SACK。`tcp_rmem` / `tcp_wmem` 及 socket 缓冲上限约 14 MiB，接口队列为 fq_codel，采样时无队列丢包。文件连接 RTT 约 210–235ms，已有接收窗口约 0.8–3.7 MiB；CPU、内存和磁盘均未饱和。

[Linux 内核说明](https://docs.kernel.org/6.18/networking/ip-sysctl.html) 明确指出接收缓冲可以自动增长，而显式设置 SO_RCVBUF 会关闭该 socket 的自动调节。网络对照使用临时文件连接测试，不把“更大缓冲”或再次启用 BBR 当作必然加速；不为本项目盲改其他服务共用的全局网络参数。

Telegram 的候选文件地址从当次 `help.getConfig` 读取，限定同一 DC；不修改账号主 DC、Session 地址、DNS 或默认路由。[Telethon 传输模式](https://docs.telethon.dev/en/stable/modules/network.html) 的 Full、Abridged、Obfuscated 均作为诊断对照，避免依据单次 ping 选择吞吐路线。

节点/传输模式按部署单独设置：`DOWNLOAD_DC_STRATEGY=primary|alternate`、`DOWNLOAD_TRANSPORT=native|abridged|obfuscated`。默认 primary/native 保留原行为；alternate 只能选 Telegram 当前配置中同 DC、同地址族、同 media/CDN 角色的备用地址。不存在备用地址时仍用原地址。网络建连失败会临时回退原线路，RPC 限流和取消原样传递。

初筛的 8 MiB 样本中，默认 `.60` 地址约 619KB/s；备用 `.54` Full 约 2.18MB/s、Abridged 短时约 13.76MB/s。随后较大样本测到备用 Abridged 四连接 32 MiB 约 3.25MB/s、八连接 64 MiB 约 2.64MB/s；备用 Full 八连接 32 MiB 约 7.35MB/s。峰值波动很大，不能拿短样本当作生产稳定速度。

连续新建授权触发过 ExportAuthorization 接口的约 27 分钟 FloodWait；测试立即停止该接口并安全暂停原 23 个未完成任务，修复旧逻辑将等待误判为普通网络失败的问题。新文件池仅首次为同账号同 DC 建立独立文件授权，后续连接使用同一个**内存文件 auth key**、独立随机 MTProto session ID；不复制账号主 Session/key，不跨服务器共享，不落盘。在空闲回收后仍可复用文件授权，账号退出/应用停止清除。该方式遵循 [Telegram 文件连接说明](https://core.telegram.org/api/files#general-considerations)。

FloodWait / FloodPremiumWait 会保留实际 `.part` 字节和重试预算，在数据库记录账号的等待截止时间；即使重启或手动点继续也遵守截止时间，其他账号仍可下载。等待结束后自动领取原任务，保留用户暂停/取消选择。测试的下一轮必须等服务端要求的时间结束，不反复调用受限接口。

## 授权复用后的对照

遵守服务端等待后，用同一份内存文件授权完成下面整轮对照；**全程 ExportAuthorization 只调用一次**。每条连接的 MTProto session ID 均不同，文件 key 与账号主 Session key 不同；每个样本的 SHA256 与已有断点一致。时间只计读取，另外约 4–11 秒用于首次建连和预热。

| 文件线路与传输 | TCP 数 | 样本 | 实测 MB/s（十进制） |
| --- | ---: | --- | ---: |
| 原入口 Full | 4 | 单文件 16 MiB | 0.877 |
| 原入口 Full | 8 | 单文件 16 MiB | 0.645 |
| 备用入口 Full | 4 | 单文件 32 MiB | 5.472 |
| 备用入口 Full | 8 | 单文件 64 MiB | 1.966 |
| 备用入口 Abridged | 4 | 单文件 32 MiB | 5.305 |
| 备用入口 Abridged | 8 | 单文件 64 MiB | 10.877 |
| 备用入口 Full | 8 | 单文件另一段 32 MiB | 5.297 |
| 备用入口 Abridged | 8 | 单文件另一段 32 MiB | 9.840 |
| 备用入口 Abridged，SO_RCVBUF=4 MiB | 8 | 单文件 32 MiB | 10.387 |
| 备用入口 Abridged，socket 改用 Cubic | 8 | 单文件 32 MiB | 4.079 |
| 备用入口 Abridged | 8 | 两文件合计 64 MiB | 19.689 |
| 备用入口 Abridged，末尾复测 | 8 | 单文件 64 MiB | 3.743 |

备用线路在同一轮仍有显著波动；接收缓冲实验未证明稳定额外收益，Cubic 样本更慢，因此保留原接收自动调节和 BBR。大幅收益来自实际文件入口和传输路径的选择，不能仅凭 Abridged 减少少量包头就解释运营商路径的差异。

再扩大至两文件合计 128 MiB：8/12/16 条连接分别约 **1.937 / 2.310 / 3.900 MB/s**；末尾八连接同样双文件复测为 1.409 MB/s。16 条连接单文件 64 MiB 为 8.866 MB/s，八连接单文件末尾复测为 10.195 MB/s。单文件的短突发峰值不能代表双任务的持续速度。

因此应用默认仍为 8/8，连接硬上限增加到 **16**，允许这台 VPS 独立选择 `DOWNLOAD_PARTS=16` / `DOWNLOAD_CONNECTIONS=16`。原生迭代器测试同时覆盖 16 请求共用 8 条连接、16 请求使用 16 条连接和两个文件共享账号限额；不按任务数翻倍文件连接。生产采用的最终参数和真实队列样本记录在后续发布结果中。

## VPS → 本机的可选 HTTPS 入口

测试电脑通过 VPS 直连保存 16 MiB，单 HTTP Range 两轮约 175KB/s / 85KB/s，四段 Range 约 337KB/s / 395KB/s。通过 InstaBox 平台 HTTPS 入口转发同一 VPS 的原画附件，单连接约 **2.09MB/s**，四段约 **2.11MB/s**，哈希一致。该结果只代表本次测试电脑的链路，不保证每台手机的速度。

可选的 `docker-compose.relay.yml` 是独立 Nginx 项目：不挂载数据库、账号或视频目录，只转发到管理员指定的原 VPS。HTTPS 入口和 VPS 地址访问的是**同一套 VPS 账号、任务、视频和密码**；InstaBox 原 8081 应用仍独立。客户端必须通过 VPS 原管理员认证，代理不注入登录 Cookie、不缓存私有媒体；浏览器会话 Cookie 强制 Secure/HttpOnly/SameSite=Strict。容器只读、无 capability、64 MiB 内存上限。

```bash
# 在 InstaBox 项目目录执行；VPS 原 8080 与 InstaBox 原 8081 均保留
cd /data/workspace/tg-web-archive
RELAY_UPSTREAM=84.54.3.25:8080 docker compose -p tg-web-archive-vps-relay -f docker-compose.relay.yml config --quiet
RELAY_UPSTREAM=84.54.3.25:8080 docker compose -p tg-web-archive-vps-relay -f docker-compose.relay.yml up -d --wait
instabox-port publish 8084
curl -fsS http://127.0.0.1:8084/health

# 查看状态或单独移除加速入口，不影响两个 app 或它们的数据
RELAY_UPSTREAM=84.54.3.25:8080 docker compose -p tg-web-archive-vps-relay -f docker-compose.relay.yml ps
RELAY_UPSTREAM=84.54.3.25:8080 docker compose -p tg-web-archive-vps-relay -f docker-compose.relay.yml down
instabox-port unpublish 8084
```

入口依赖 InstaBox 和 VPS 均在线；VPS 内部维护重启时该入口也会短暂不可用。它不会把 Telegram 文件传输改道，Telegram → VPS 的节点选择仍由文件连接配置控制。未改变原外部保活。

HTTPS 在 InstaBox 平台入口终止，Nginx 回源到现有 VPS 的 HTTP 8080；当前回源段没有新增 TLS。不要将它描述为两台服务器之间的端到端 HTTPS 隧道。

## 管理与回退

实际目录、端口、备份及更新流程沿用 [完整双机说明](DOWNLOAD_CONNECTIONS_20261023.md#更新管理与回滚)。更新后验证原账号授权、全部原任务、断点进度非递减、源码/cryptg、SQLite 与公网健康；保持 Akile、Komari、1Panel 和外部保活原状态。

若八连接环境出现异常，可在原 `.env` 设置 `DOWNLOAD_PARTS=4`、`DOWNLOAD_CONNECTIONS=4` 并重新创建 app；设置连接数为 1 关闭专用池，分片数为 1 顺序读取。只调整下载参数，不改密码、不重新登录、不恢复旧数据库。旧应用代码为 `aa56d25`（包含第一轮文件池），也可以使用更新前备份的旧镜像重建 app，继续挂载现有数据。
