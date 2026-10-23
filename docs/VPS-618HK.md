# VPS 84.54.3.25:8080 部署与运维

> 后续原画播放器升级已取代下文的默认 480P/自动降级策略。当前始终默认原画，手机连续拖动与原编码分片、最新部署和验收以 [原画播放器交接](ORIGINAL_PLAYER_20261023.md) 为准；下文版本与耗时保留作历史记录。

记录日期：2026-10-23（北京时间）。本文件不包含密码、SSH 私钥、Session 或任何密钥值。

最新应用为 `fce63e4`；本轮保留 `.env` 原字节与现有授权，已验证默认 480P、真实 30:00 跳转约 1.12 秒、画质切换保留进度、本机完整测试文件下载与 ZIP 解压。历史初次迁移步骤保留在下文，本轮更新与新备份以 [最新升级记录](UPGRADE_20261023.md) 为准。

## 实例

| 项目 | 值 |
| --- | --- |
| 公网入口 | `http://84.54.3.25:8080` |
| 系统 | Debian 13，2 vCPU，约 2 GB 内存 |
| 代码目录 | `/opt/telegram-video-manager`（Git 工作树） |
| Git 远端 | `https://github.com/fengbule/tg-web-archive.git` |
| 已部署应用提交 | `fce63e48619127c23d99f6fa9d2ab7528bf7b871` |
| Compose 项目 | `telegram-video-manager` |
| 容器 | `telegram-video-manager`、`telegram-video-manager-nginx` |
| 数据目录 | `/data/telegram-video-manager`（独立 246 GB 数据盘） |
| 端口 | 宿主机 `8080` → Nginx `80` → 应用 `8000` |
| 最新备份 | `/root/backups/tg-web-archive-20261023T004509Z-seek-upgrade`（旧备份也保留） |

`.env` 从旧部署原样保留（`ADMIN_PASSWORD_HASH_B64`、`SESSION_SECRET`、`CONFIG_ENCRYPTION_KEY` 等），只追加了 `AUTO_SMOOTH=true` 和 `APP_VERSION=2.0.0`。管理员密码未修改；数据库中已有 `admin_password_pbkdf2` 时仍以数据库为准。

## 本次升级做了什么

1. 部署前用 SQLite Online Backup API 生成一致数据库快照，并打包 `session`、`config`、`thumbnails`、`database` 到备份目录，权限 600。
2. 移走旧代码到备份目录；从 GitHub 拉取 `main` 到原路径，复制回原 `.env`。
3. 用新的 `docker-compose.yml` 构建并启动应用与 Nginx。旧容器的 bind mount 数据目录不变。
4. 启动后媒体优化 worker 自动执行：
   - 将原 MP4 的 `moov` 索引从文件尾移动到文件头（`-movflags +faststart`，`-c copy` 无损）；
   - 生成 480P H.264/AAC 流畅版 `*.smooth.mp4`，不覆盖原画。
5. 数据库自动新增 `faststart`、`smooth_*` 列；旧 `accounts`、`media`、`downloads` 记录保留。

## 日常命令

```bash
cd /opt/telegram-video-manager

docker compose ps
docker compose logs --tail=100 app
docker compose restart
curl -fsS http://127.0.0.1:8080/health

# 更新代码
cd /opt/telegram-video-manager
git fetch origin
git merge --ff-only origin/main
docker compose up -d --build

# 只重启应用，不动 Nginx
docker compose restart app
```

不要执行 `docker compose down -v`，不要删除 `/data/telegram-video-manager`。

## 备份与回滚

部署前备份：

```bash
BK=/root/backups/tg-web-archive-$(date +%Y%m%d-%H%M%S)
mkdir -p "$BK" && chmod 700 "$BK"
docker exec -i telegram-video-manager python - <<'PY'
import sqlite3
s=sqlite3.connect('/data/telegram-video-manager/database/app.db')
d=sqlite3.connect('/data/telegram-video-manager/database/app.db.backup')
with d: s.backup(d)
d.close(); s.close()
PY
cp /data/telegram-video-manager/database/app.db.backup "$BK/app.db"
tar -C /data/telegram-video-manager -czf "$BK/private-data.tar.gz" session config thumbnails database
chmod 600 "$BK"/*
```

回滚代码（数据兼容时）：

```bash
cd /opt/telegram-video-manager
git log --oneline -5
git checkout <旧提交>
docker compose up -d --build
```

本次新增列是向后兼容的。若要回到本次升级前的旧镜像，需同时恢复备份中的 `.env` 与 `data/`，因为旧代码不认识新列；不要把新数据库直接交给非常旧的版本。

## 播放加速说明

- 原文件索引已移动到文件头，浏览器不再需要先读取 1.6 GB 文件的尾部。
- 原画码率约 4 Mbps；该 VPS 到部分中国网络的实测单连接吞吐可能只有 0.7–1.5 Mbps，因此慢网络下应切换到 480P 流畅版。
- 本次 55 分钟视频的 480P 文件约 84 MB（约 200 kbps）；最新发布默认使用流畅版，实测从开头拖到 30:00 后 1.12 秒恢复播放。该值是单次公网实测，线路变化会影响结果。
- `AUTO_SMOOTH=true` 会让新下载的视频自动生成流畅版；如需节省 CPU，可在 `.env` 改为 `false` 后重启 app，媒体库仍有手动“生成 480P”入口。
- 流畅版文件位于原视频同目录，文件名以 `.smooth.mp4` 结尾；删除视频时会一并清理。

## 已完成验收

- 新 UI 公网加载、登录页、仪表盘、媒体库、播放器、账号页、设置页无脚本错误。
- 原账号 `账号 1`（养乐多）仍为 `authorized`，Session 未删除。
- 管理员密码哈希与部署前 `.env` 一致。
- `moov` 位于偏移 32，`mdat` 在其后。
- 原画与 480P 均支持 HTTP Range 206；下载响应带 `attachment` 和中文文件名。
- 批量下载 ZIP 返回 `application/zip`。
- 480P 播放与 30 分钟跳转通过。

## 待观察

- 该 VPS 的国际线路质量波动较大；若原画仍卡顿，优先使用 480P。
- `AUTO_SMOOTH` 单 worker 会占用约一个 CPU 核；生成 55 分钟 480P 约需十余分钟，期间不影响已有播放。
- 未修改 1Panel、Komari 或其他系统服务。
