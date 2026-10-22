# 2026-10-23 双实例升级验收

## 版本

- 仓库 `main`：`7ba4f2ce9e941ce6618961e3a521e28c58f5de3e`
- 变更：faststart 播放索引、480P 流畅版、扫码/手机号双登录、深色控制台 UI、原画/批量下载。
- 自动测试：47 passed，1 failed，1 skipped。唯一失败是 `tests/test_init_instabox.py` 在 Windows 上调用 `os.getuid`（Linux 专用脚本），与本次业务改动无关。

## VPS `84.54.3.25:8080`

- 代码目录 `/opt/telegram-video-manager`，提交 `7ba4f2c`，应用与 Nginx 容器 healthy，`/health` 200。
- 部署前一致备份：`/root/backups/tg-web-archive-20261022-162837-pre`（`app.db` 65536 B，私有数据 998349 B）。
- 原有账号保留：`accounts=1`，`authorized=True`，名称“养乐多”。
- 管理员密码：`.env` 原哈希保留，未修改；数据库内密码记录未改动。
- faststart：原 MP4 `moov` 位于偏移 32，`mdat` 位于 3,598,471；大小由 1,667,203,765 变为 1,668,231,365。
- 480P：`*.smooth.mp4` 83,883,498 B（约 202 kbps），状态 `ready`。
- 播放跳转：480P 从 0 秒跳到 30:00，`seek_seconds=2.55`，随后 `currentTime=1804.96` 且继续播放；缓冲区已扩展到 1797–1807、1903–2053 秒。
- 下载：`GET /api/media/6/stream?download=true` + Range 返回 206、`Content-Disposition: attachment`、正确中文文件名；批量 ZIP 返回 `application/zip` 和 `PK` 头。
- 无头 Chromium 1440×950 与 390×844：登录、仪表盘、媒体库、播放器、Telegram 登录、设置页无 console/page error。
- 单连接外部吞吐实测约 0.7–1.5 Mbps，原画 4 Mbps 不适合直接串流；480P 是慢线路的推荐画质。

## InstaBox

- 机器 `m_agqv47q5at4mzg6nr336pvg33u`，代码目录 `/data/workspace/tg-web-archive`，提交 `7ba4f2c`。
- 部署前备份：`backups/tg-web-archive-20261022T172808Z.tar.gz`。
- 新镜像 `tg-web-archive-app:7ba4f2ce9e94`，应用与 Nginx healthy，本地 `/health` 200，公网 `https://8081-agqv47q5at4mzg6nr336pvg33u.instabox.tech/health` 200。
- 数据库新增 `faststart` / `smooth_*` 列；原有 `accounts=1` 保留。
- 原管理员密码登录返回 200；账号 `authorized=True`（xiao wan），Session 保留。
- Akile 容器保持运行；`komari-agent` 为 active/running。
- 部署由平台 exec 在后台完成，检查了 `exitCode=0`、`timedOut=false`，未只依赖 HTTP 200。

## 回滚

- VPS：见 `docs/VPS-618HK.md`；旧代码在备份目录 `code-old`，数据兼容新列。
- InstaBox：旧镜像 `tg-web-archive-app:e9f77a571fd4` 仍在，按 `docs/INSTABOX.md` 使用旧 `IMAGE_TAG` 回退；涉及结构变更时同时恢复配套 `.env` 与 `data/`。

## 未执行/待观察

- 未修改 VPS 管理员密码，也没有执行真实“结束会话”测试。
- 未在 VPS 上实际下载完整 1.6 GB 文件到手机/电脑，只验证了 Range、附件头和 ZIP 响应。
- 未让 InstaBox 生成 480P（该实例媒体库为空，且默认 `AUTO_SMOOTH=false`）。
- 两个实例的真实扫码登录未在本轮重新执行；账号现有 Session 均保持 authorized。
