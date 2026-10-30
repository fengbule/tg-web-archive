# Telegram 客户端工作区

在侧栏打开 **Telegram 客户端**。本次将原简版消息页整理为可在手机、平板、电脑使用的会话工作区。仍使用已有 Telegram 用户账号及 API/扫码登录，保留默认原画、下载、收藏、密码与账号备份；不重新引入画质增强。

## 已实现

- 会话按全部、未读、频道、群组、私聊、机器人、归档分类；按标题或用户名搜索已加载会话，继续加载更多会话。置顶、归档、静音与已读操作同步到 Telegram。
- 时间顺序消息、保留阅读位置加载更早记录、搜索会话内消息、刷新、后台轮询新消息。阅读历史不会自动把整个会话标为已读；用户可明确标记截至当前已显示消息的已读状态。阅读旧记录时新消息不会强制滚到底部。
- 纯文本发送、回复、编辑/删除自己发送的消息、机器人按钮与链接。文字按原样发送，不把 Markdown/HTML 误当富文本。Enter 换行，Ctrl/⌘+Enter 或发送按钮发送，中文输入法确认不会误发。
- 草稿仅暂存当前标签页内存，按账号和会话分开；不写服务器数据库或浏览器持久存储，关闭/刷新标签页即清除。失败保留输入，不自动重发；服务超时先刷新确认消息是否已发送。
- 从服务器媒体库选择视频加入持久化上传队列，明确捕获发送账号和目标会话，遵守来源内容保护。视频仍保存在服务器；本机下载和原画播放入口保留。
- 用 @用户名、公开 t.me 链接或私有邀请链接预览。预览私有邀请只调用 CheckChatInvite，不偷偷加入；用户明确点击加入/订阅或启动机器人后才发送请求。需要审批的邀请显示“已申请，等待管理员批准”。
- 退出群组/频道需要在界面明确确认；不删除账号、已下载媒体、下载记录或收藏。不提供一键退出自己创建的群组/频道或删除会话历史，避免与普通退出混淆。只读频道禁用发送，服务端以 Telegram 实际权限为准。

## 账号、接口与隐私

新接口统一在 `/api/client`，全部沿用原管理员认证，**必须显式提供 `account_id`**，避免多标签页切换全局活动账号时发错账号。前端捕获导航与会话代次，迟到响应不能覆盖新会话。消息与会话历史直接向 Telegram 读取，不新增本地历史数据库；返回正文只在已认证接口内，不写应用日志或公共文档。

`GET /dialogs` 返回 `items`、`next_cursor`，游标绑定账号与归档分类；`GET /dialogs/PEER/messages` 支持 `offset_id`、`after_id`、`q`。`POST .../messages` 接受 `text`、`reply_to`、UUID `request_id`；运行中的同账号服务会抑制最近 128 个相同请求的重复发送，这不是跨重启的恰好一次投递保证。`PATCH/DELETE .../messages/ID` 编辑/删除自己的消息。`POST .../actions` 支持 `read/pin/mute/archive/leave`；`POST /target/preview`、`/target/join` 做目标预览和明确加入。原 `/api/outbox` 新增可选 `account_id`，原接口调用者保持兼容。

Telegram 限流返回 429 与 Retry-After；无权限 403；邀请失效或目标不可访问 404；请求未接受 409；超时 504。不会自动加入陌生频道或批量发送。当前工作区以文字、频道订阅和服务器视频任务为主，语音/视频通话、秘密聊天和任意附件的 Telegram 内联播放器不在本次实现范围。

## 双机部署和管理

部署目录与端口保持不变：VPS `/opt/telegram-video-manager`，Compose `telegram-video-manager`，公网 8080；InstaBox `/data/workspace/tg-web-archive`，Compose `tg-web-archive`，8081，外部 VPS 继续保活。Akile 3000、Komari、birth、chiken、流量服务和 8084 中转不属于本次部署操作对象。

更新前的受保护备份：VPS `/root/backups/tg-web-archive-client-20261030T124529Z`；InstaBox `backups/tg-web-archive-client-20261030T124527Z`。含一致性 SQLite/Session、配置和旧缩略图；不会复制原视频或把凭据提交仓库。实际连接路径与私有报告见操作者 `output/tg-web-archive/部署交接.md`。

```sh
# VPS
cd /opt/telegram-video-manager
git fetch origin && git merge --ff-only origin/main
docker compose -p telegram-video-manager build app
docker compose -p telegram-video-manager up -d --no-deps --force-recreate --wait app
docker compose -p telegram-video-manager restart nginx
curl -fsS http://127.0.0.1:8080/health

# InstaBox；IMAGE_TAG 同时写入原 .env，其他配置行保持不变
cd /data/workspace/tg-web-archive
git fetch origin && git merge --ff-only origin/main
export IMAGE_TAG="$(git rev-parse --short=12 HEAD)"
docker compose -p tg-web-archive -f docker-compose.instabox.yml build app
docker compose -p tg-web-archive -f docker-compose.instabox.yml up -d --no-deps --force-recreate --wait app
python3 - <<'PY'
import os, tempfile
from pathlib import Path
p=Path('.env')
lines=[line for line in p.read_text().splitlines() if not line.startswith('IMAGE_TAG=')]
lines.append('IMAGE_TAG='+os.environ['IMAGE_TAG'])
with tempfile.NamedTemporaryFile(mode='w',dir=p.parent,delete=False) as f:
    f.write('\n'.join(lines)+'\n'); f.flush(); os.fsync(f.fileno())
os.replace(f.name,p)
PY
docker compose -p tg-web-archive -f docker-compose.instabox.yml restart nginx
curl -fsS http://127.0.0.1:8081/health
```

管理日志用各自 `docker compose ... logs --tail 100 app`，重启仅 `... restart app`。本次无数据库迁移。若需回滚，使用源码 `d447742` 和更新前保存镜像 `tg-web-archive-vps-rollback:client-20261030` / `tg-web-archive-app:rollback-client-20261030`，只替换本项目 app 并重启其 nginx，保留现有 `.env`、DB、Session、media，InstaBox 同步正确的 IMAGE_TAG。不要 `down -v` 或恢复旧 DB 覆盖新下载。Telegram 已成功执行的加入、退出、发送、已读等操作不因代码回滚而撤销。

## 验证方式

`tests/test_telegram_client.py` 使用真实 Telethon 请求类型的模拟客户端检查频道权限、分页游标、账号隔离、纯文本回复、重复点击、编辑归属、置顶/静音/归档/已读/退出及邀请审批。`tests/client_api_smoke.py` 检查匿名拒绝、必填账号、校验、限流/权限映射和上传账号隔离。`tests/telegram_client_ui.mjs` 在无头浏览器使用合成消息验证操作、草稿、转义、迟到响应和多种屏幕/明暗布局；这些操作不会向真实联系人发送消息或退出真实频道。

## 本次发布记录

应用源码版本 `943e77b6ff58`。147 项 Linux pytest、3 组 API 和 7 组无头浏览器回归通过；最终公开频道加入后成员状态更新另用 14 项同机客户端单元测试复核通过。合成素材的手机暗色和电脑亮色界面截图已目检；原画播放/拖动、锁屏选集、封面、手机/平板/电脑视图、本机附件下载、服务器下载和增强移除回归通过。私有日志位于操作者 `output/tg-web-archive/client-20261030/`。

VPS 正常 Compose 构建。InstaBox 首次构建遭 Docker Hub 429，原应用保持运行；核对 `git diff d447742 HEAD -- Dockerfile requirements.txt` 无差异后，用本机已保存的 `tg-web-archive-app:ba5a7dca567f`（相同依赖）作基础，仅复制最新 `app` 构建新镜像，未升级依赖。复现用备份目录内的 `Dockerfile.local-base` 执行 `docker build --pull=false -f backups/tg-web-archive-client-20261030T124527Z/Dockerfile.local-base -t tg-web-archive-app:943e77b6ff58 .`，随后执行上述仅替换 app、同步 IMAGE_TAG、重启本项目 nginx 的步骤。此办法仅适用于依赖与基础版本一致的发布；成功记录在 `deploy-offline.log`，unit 为 `tg-web-archive-client-offline-20261030`。

两台运行容器的前后端文件均与发布源码逐字节一致且健康。VPS 1 个授权账号、74 条媒体、74 条下载、1 条发件箱、5 个收藏及原文件大小保持；InstaBox 1 个授权账号保留，本地生产媒体库为空。密码/API/Session 指纹、其他配置与无关服务未变，SQLite 检查 ok。回滚只替换代码/镜像，不能用旧数据库覆盖这些记录。

三个公网入口已核对静态资源、真实 Telegram 会话列表/少量频道历史/权限、手机界面选择/工具/返回，全部通过；匿名和伪造会话被拒绝，新浏览器仍需原密码。VPS 原视频 Range 206 正常。真实验证仅做读取，没有发送消息、加入/退出频道、标已读或修改 Telegram 设置；写操作由上述隔离测试验证。应用已构建版本保持 `943e77b6ff58`，文档收尾提交不再重建应用。

- VPS：<http://84.54.3.25:8080>。
- HTTPS 中转：<https://8084-agqv47q5at4mzg6nr336pvg33u.instabox.tech>。
- InstaBox：<https://8081-agqv47q5at4mzg6nr336pvg33u.instabox.tech>。
