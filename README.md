# Telegram 视频管理器

面向私人使用的中文 Web 系统。使用 Telegram **用户账号**（Telethon）收发消息、与机器人互动、管理频道视频，将文件保存到服务器数据盘，并提供任务队列、媒体库、HTTP Range 在线播放和磁盘保护。

本项目不会绕过 Telegram 权限或内容保护，只能访问当前登录账号原本可以查看和下载的内容。

## 最快部署方法

```bash
git clone https://github.com/fengbule/tg-web-archive.git
cd tg-web-archive
sudo bash scripts/manage.sh install
```

脚本会用中文提示你设置管理员密码，自动生成加密配置、创建 `/data` 持久化目录并启动 Docker Compose。安装完成后访问 `http://服务器IP:8080`。

如果你让 AI 辅助部署，可以直接告诉它：

> 阅读本仓库 README 和 scripts/manage.sh，在不删除服务器其他数据的前提下安装 Docker、运行 `sudo bash scripts/manage.sh install`，并检查健康接口。不要输出或提交 `.env`、Telegram Session、验证码、密码、API ID/API Hash。

## 功能

- 管理员密码登录（bcrypt 哈希保存、HttpOnly 会话 Cookie）
- Telegram API ID/API Hash 加密落盘，手机号、验证码和两步验证密码不保存
- 系统设置中可查看和复制当前账号的 API ID/API Hash；查看前必须重新验证管理员密码，关闭窗口后立即从页面清除
- 管理员登录密码可在页面修改；保存后全部旧会话立即失效，必须使用新密码重新登录
- 可设置独立的“查看密码”保护 API 凭据，也可随时恢复为使用管理员密码查看；所有密码只保存 PBKDF2 哈希
- 支持多个 Telegram 用户账号，每个账号使用独立 Session，可随时切换
- 新增账号可安全复用已加密的 API 凭据，通常只需验证新手机号
- Telegram Session 持久化，支持分别退出和清除
- 会话列表、未读数量、历史消息分页和新消息增量刷新
- 电脑侧边栏和手机底部栏都提供独立的“⭐ 我的收藏夹”页面，无需在会话列表中搜索自己
- 向私聊、群组和机器人发送文字，支持普通机器人按钮
- 通过用户名或链接查找目标，加入/退出频道和群组，启动机器人
- 只允许删除当前账号自己发送的消息，退出频道需要二次确认
- 从媒体库向会话发送普通视频，使用持久化后台发送队列显示进度
- 媒体库每个视频提供“⭐ 上传收藏夹”快捷按钮；上传前检查来源权限，上传后在收藏夹持续显示等待、进度、成功或失败状态
- Telegram 内容保护来源不会通过媒体库重新发送
- 已加入频道搜索、视频消息分页浏览、批量选择
- 两路并发下载、实时进度/速度、网页暂停/继续、取消、自动重试和真实断点续传
- 网络中断自动续传最多 3 次；容器更新和服务器重启保留 `.part` 文件并从已有字节继续
- `(频道 ID, 消息 ID)` 唯一约束，避免重复任务
- `.part` 临时文件，完成后原子移动为正式文件
- 频道视频显示 Telegram 原封面并在数据盘缓存
- 本地媒体库搜索/排序、重命名、详情、删除和 FFmpeg 缩略图
- 媒体库支持复选框、全选当前结果、删除选中项和一键清空全部视频
- 原生播放器与 HTTP Range，支持拖动进度；不兼容格式可下载原文件
- 仪表盘显示磁盘、视频、临时文件和任务统计
- 下载前和下载中均检查磁盘保护线
- 响应式中文界面，适配手机和电脑；手机端播放器接近全屏并适配触控按钮、底部安全区域和竖屏信息布局

## 目录

```text
app/main.py                 Web API、安全认证、媒体管理与 Range 响应
app/telegram_service.py     Telegram 登录、频道和消息浏览
app/downloader.py           双 worker 下载队列、进度、磁盘保护、FFmpeg
app/outbox.py               持久化媒体发送队列和上传进度
app/db.py                   SQLite 数据结构和重启恢复
app/static/                 中文单页 Web 界面
tests/                      核心测试与 API 冒烟测试
Dockerfile                  FastAPI + Telethon + FFmpeg 镜像
docker-compose.yml          应用和 Nginx，自动重启
nginx.conf                  反向代理和安全响应头
.env.example                环境变量模板（不含秘密）
```

持久化目录固定在 `/data/telegram-video-manager`：

```text
media/       正式视频
temp/        临时下载
database/    SQLite 数据库
session/     Telegram Session
config/      预留配置目录
thumbnails/  视频缩略图
```

## 首次部署

### 中文菜单（推荐）

进入项目目录后运行：

```bash
sudo bash scripts/manage.sh
```

选择 `1) 安装/启动`。脚本会引导设置管理员密码，自动生成安全配置、创建 `/data` 目录并启动容器。以后更新、查看状态、日志、备份和卸载都使用同一个菜单。

### 手动部署

1. 安装 Docker Engine 和 Compose 插件。
2. 将项目放到 `/opt/telegram-video-manager`。
3. 创建 `/data/telegram-video-manager` 及上述子目录。
4. 复制 `.env.example` 为 `.env`，生成以下值：

   - `ADMIN_PASSWORD_HASH_B64`：管理员密码的 bcrypt 哈希再经 Base64 编码后的值。
   - `SESSION_SECRET`：至少 32 字节随机值。
   - `CONFIG_ENCRYPTION_KEY`：Python Fernet 密钥。

5. 执行 `docker compose up -d --build`。
6. 访问 `http://服务器地址:8080`。生产环境建议把 8080 放在防火墙/VPN 后，或在外层反向代理配置 HTTPS，并将 `COOKIE_SECURE=true`。

Telegram API ID 和 API Hash 可从 Telegram 官方开发者页面申请，并在首次登录向导中输入。验证码和两步验证密码只用于当次登录，不会保存。

## 添加和切换 Telegram 账号

1. 登录管理后台后，点击页面右上角的 `＋ 账号`，或进入“系统设置 → 账号管理”。
2. 输入一个便于识别的名称，例如“主账号”或“备用账号”。
3. 系统会为新账号创建独立 Session，并复用服务器上加密保存的 API 凭据。
4. 输入新账号手机号、验证码和两步验证密码。
5. 使用右上角账号选择器随时切换。频道列表和下载操作使用当前选中的账号；已经开始的下载任务仍由原账号继续完成。

移除账号只清除该账号在服务器上的 Telegram Session，不会删除已经下载的视频。系统始终要求至少保留一个账号槽位。

## 消息、机器人和频道管理

- “消息与机器人”页面显示当前账号的私聊、群组、频道和机器人会话。
- “我的收藏夹”是独立页面，可直接查看历史、发送文字，并用固定在输入框左侧的“＋”选择媒体库视频；消息区支持鼠标滚轮和手机触摸滚动。
- 上传到收藏夹会按本地原文件重新上传，不转发、不转码；原文件画质和码率保持不变。
- 新上传的视频消息会关联本地媒体库，点击消息中的播放卡片即可打开原画播放器并拖动进度。
- 打开会话后分页读取历史消息，并约每 2.5 秒增量检查新消息。
- 输入文字后按 Enter 发送，Shift+Enter 换行；自己发送的消息可以为双方删除。
- 点击“＋ 文件”可以从本地媒体库选择普通视频，后台发送进度会显示在输入框上方。关闭网页不会删除发送任务，服务重启后会重新排队。
- 点击“查找 / 加入”可输入 `@username`、公开 `t.me` 链接或私有邀请链接。机器人目标会发送 `/start`。
- 退出群组或频道前必须二次确认；频道发言、入群审批和机器人交互仍受 Telegram 原有权限限制。
- 本系统不会利用重新上传规避禁止转发或内容保护；检测到受保护来源时会拒绝发送。

## 暂停、继续与断点续传

- “暂停”只停止网络下载并保留 `/data/telegram-video-manager/temp/<任务ID>.part`。
- “继续”从临时文件现有字节偏移恢复，不会重新下载已经保存的部分。
- 断网、容器更新和服务器重启同样保留临时文件，任务会自动重新排队。
- “取消并删除临时文件”才会放弃已下载部分；界面会明确二次确认。
- 清理临时文件只删除没有被排队、下载中或暂停任务引用的孤立文件。

## 封面和在线播放

- 频道页优先读取 Telegram 消息自带的原封面，缓存于 `/data/telegram-video-manager/thumbnails/telegram`。
- 下载完成后，FFmpeg 会读取时长和分辨率并生成本地媒体库封面。
- 视频使用 Telegram 原始字节直接下载；FFmpeg 只生成独立 JPG 封面，不会转码、压缩或修改视频。
- 媒体库播放器直接读取同一个原始文件，支持 HTTP Range 和拖动进度，不降低分辨率或码率。
- 生产部署由 FastAPI 完成权限校验，再通过 Nginx `X-Accel-Redirect` 和 `sendfile` 直接传输视频；媒体目录仍为 `internal`，不能绕过登录直接访问。
- 视频 Range 片段使用一小时私有浏览器缓存，播放器启用自动预缓冲，减少反复快进时的重复传输。
- 电脑端使用宽屏播放窗口，页面显示“原画直播放 · 未转码”、原始分辨率、文件大小和估算平均总码率。
- MP4/H.264 等浏览器兼容格式可直接播放；遇到浏览器不支持的编码会显示中文提示，并保留下载原文件入口。

## 删除视频

- 单个删除：媒体卡片点击“删除”。
- 批量删除：勾选多个视频后点击“删除选中”。
- 全选当前搜索结果：勾选工具栏的“全选当前结果”。
- 一键清空：点击“一键清空全部”，并输入 `清空全部视频` 完成二次确认。

删除操作会同步清理正式视频、缩略图、对应临时文件、下载任务和数据库记录，但不会删除 Telegram 上的原消息。一键清空影响所有 Telegram 账号下载到本机媒体库的视频。

## 更新

```bash
cd /opt/telegram-video-manager
sudo bash scripts/manage.sh update
```

更新不会删除 `/data` 中的数据。不要执行 `docker compose down -v`，也不要手工删除持久化目录。

正在下载时也可以正常更新：服务关闭会把任务重新放回队列并保留临时文件，容器启动后从已有字节偏移继续下载。也可以先在页面点击“暂停”，更新完成后再点击“继续”。只有明确点击“取消并删除临时文件”时才会放弃已有数据。

## 备份与恢复

建议先短暂停止容器，保证 SQLite 与 Session 一致：

```bash
cd /opt/telegram-video-manager
docker compose stop
tar -C /data -czf /安全备份位置/telegram-video-manager-$(date +%F).tar.gz telegram-video-manager
docker compose start
```

恢复时停止容器，将备份解压回 `/data`，确认所有者和权限后再启动。`.env` 含会话签名和配置解密密钥，应单独安全备份；缺失 `CONFIG_ENCRYPTION_KEY` 将无法读取已保存的 Telegram API 凭据。

## 运维

```bash
sudo bash scripts/manage.sh status
sudo bash scripts/manage.sh logs
sudo bash scripts/manage.sh backup
sudo bash scripts/manage.sh reset-password
sudo bash scripts/manage.sh uninstall
```

普通卸载会保留所有视频和数据库。永久删除数据必须额外使用 `uninstall --purge-data` 并输入中文确认文字，避免误删。

日志不主动记录密码、验证码、手机号、API Hash 或 Session。排查问题时也不要粘贴 `.env`、`session/` 或数据库内容。

如果忘记管理员密码，可在服务器项目目录执行 `sudo bash scripts/manage.sh reset-password`。脚本会要求输入两次新密码，更新哈希、让所有旧登录失效并重启容器，不会删除视频、数据库或 Telegram Session。

## 限制

- 单管理员，可管理和切换多个 Telegram 用户账号；每个账号使用独立 Session。
- 消息采用短轮询增量刷新，不包含语音/视频通话、秘密聊天或 Telegram Web App 完整渲染。
- 普通机器人文字、命令和按钮可用；支付、验证码、复杂小程序等流程可能需要返回官方客户端。
- 媒体发送任务可以跨服务重启重新排队，但 Telegram 上传协议本身不保证跨进程按字节续传。
- 第一版不自动转码；浏览器不支持的编码/封装需下载原文件播放。
- Telegram 实际登录、频道读取和真实视频下载必须由账号持有人完成验证。
- HTTPS 需要现有域名和证书；无域名的测试部署默认使用 8080 HTTP，建议仅私人网络使用。
