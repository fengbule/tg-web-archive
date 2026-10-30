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
docker compose -p tg-web-archive -f docker-compose.instabox.yml restart nginx
curl -fsS http://127.0.0.1:8081/health
```

管理日志用各自 `docker compose ... logs --tail 100 app`，重启仅 `... restart app`。本次无数据库迁移。若需回滚，使用源码 `d447742` 和更新前保存镜像 `tg-web-archive-vps-rollback:client-20261030` / `tg-web-archive-app:rollback-client-20261030`，只替换本项目 app 并重启其 nginx，保留现有 `.env`、DB、Session、media，InstaBox 同步正确的 IMAGE_TAG。不要 `down -v` 或恢复旧 DB 覆盖新下载。Telegram 已成功执行的加入、退出、发送、已读等操作不因代码回滚而撤销。

## 验证方式

`tests/test_telegram_client.py` 使用真实 Telethon 请求类型的模拟客户端检查频道权限、分页游标、账号隔离、纯文本回复、重复点击、编辑归属、置顶/静音/归档/已读/退出及邀请审批。`tests/client_api_smoke.py` 检查匿名拒绝、必填账号、校验、限流/权限映射和上传账号隔离。`tests/telegram_client_ui.mjs` 在无头浏览器使用合成消息验证操作、草稿、转义、迟到响应和多种屏幕/明暗布局；这些操作不会向真实联系人发送消息或退出真实频道。
