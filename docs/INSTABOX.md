# InstaBox 部署、测试与交接

本说明对应 2026-10-22 的私人测试部署。仓库初始 `ACCEPTANCE_TEST.md` 是历史报告，不能作为本实例真实 Telegram 登录、下载或上传成功的证据。实际地址、管理员密码、平台连接凭据和验收产物保存在操作者的受保护目录，不提交 Git。

## 实例边界

本次已确认目标 InstaBox 为 Debian 13、4 核、约 8 GB 内存，`/data` 独立持久化盘约 20 GB。现有 Akile 使用回环 3000，Komari 为独立 systemd 服务。新应用使用：

| 项目 | 值 |
| --- | --- |
| 源码目录 | `/data/workspace/tg-web-archive` |
| Compose 文件 / 项目名 | `docker-compose.instabox.yml` / `tg-web-archive` |
| 容器 | `tg-web-archive-app-1`、`tg-web-archive-nginx-1` |
| 宿主机端口 | `127.0.0.1:8081` |
| 数据目录 | 项目内 `data/`，位于 `/data` 持久化盘 |
| 独立卷 | `tg-web-archive_archive-data`，local bind 指向本项目 `data/` |
| 容器内数据目录 | `/data/telegram-video-manager` |
| 公网入口 | `instabox-port publish 8081` 提供的 HTTPS |
| 下载保护线 | 5 GiB；并发 2 路 |

应用以宿主部署用户 UID/GID 运行，移除 Linux capabilities；私有目录 700，`.env` 和客户端配置 600，媒体目录 755。Nginx 仅以只读方式挂载媒体目录。应用和代理配置自动重启、健康检查及日志轮转。保活继续由外部 VPS 执行；此项目不安装、修改或重启保活、Akile、其数据库或 Komari。

## 首次安装

需要 Git、Python 3、Bash、Docker Engine、Compose（支持 `up --wait`）、`instabox-port`，以及当前用户的 Docker 权限。先通过平台接口核对机器 ID，并在机内检查：

```bash
hostname
id
nproc
free -m
df -h /data /
docker ps --format '{{.Names}} {{.Ports}} {{.Status}}'
ss -ltn
docker compose version
command -v instabox-port
```

确认目标目录不存在且 8081 空闲后：

```bash
cd /data/workspace
git clone https://github.com/fengbule/tg-web-archive.git
cd tg-web-archive
bash scripts/instabox.sh init
```

`init` 交互读取至少 16 位管理员密码，只保存 PBKDF2 哈希；自动化时可从受保护文件通过标准输入提供密码，禁止把实际密码写进命令参数或记录。已有 `.env` 会原样保留；有数据却缺少 `.env` 时拒绝重新生成密钥。不要 `source .env`，不要输出 `docker compose config` 的完整展开结果。

一般部署可在网页中输入自己的 Telegram API 凭据。私人扫码试验可按下一节先启用测试配置，再启动：

```bash
bash scripts/instabox.sh deploy
bash scripts/instabox.sh status
```

`deploy` 构建按 Git 提交命名的应用镜像，等待两个容器健康，再发布独立端口，并将成功部署的镜像标签保存到 `.env` 的 `IMAGE_TAG`。平台 HTTPS 终止后由本地 Nginx 转发；Cookie 强制 Secure、HttpOnly、SameSite=Strict。单独访问本地 HTTP 能检查健康，不能验证安全 Cookie 登录。

平台执行 API 返回 HTTP 200 不代表命令成功，必须检查 `exitCode=0`、`timedOut=false`。长构建可以使用 `systemd-run` 后台运行，分别核对 transient service 的 `Result`、`ExecMainStatus`、容器健康和公网接口；日志放项目外并设 600。不要在命令尚未完成时宣称已部署。

## 直接扫码，不要求用户填写 API

扫码流程使用 Telethon 的官方 QR 登录接口。手机 Telegram 的“设置 → 设备 → 连接桌面设备”扫描后确认；有两步验证时继续输入密码。二维码仅保存在内存，受管理员登录保护、响应 `no-store`，过期自动刷新，最多等待 5 分钟。取消、改用手机号或服务关闭会停止等待。二维码不能代替手机持有人确认；取消本地等待不保证 Telegram 已签发的短期 token 立刻撤销。

底层 MTProto 仍需应用标识。为了满足这台私人测试机“不申请、不填写 API 凭据”的试验要求，使用 Telegram 官方开源代码明确提供的测试样例：

```bash
python3 scripts/enable_test_qr.py --test-only
bash scripts/instabox.sh deploy
```

脚本从 Telegram Desktop 官方仓库取得文件对应的不可变提交，提取公开测试配置，保存至 `data/config/test-client.json`（600），并在 `.env` 中记录该文件路径。实际值不会打印或加入仓库。应用首次使用时将配置加密写入 SQLite；已有账号配置不会被覆盖。新账号可复用已配置的应用标识。

这实现的是**用户无需填写 API 的测试登录**，不是不使用 Telegram 协议，也不是伪装成 Telegram 官方客户端。测试样例存在服务器限制，可能出现 `API_ID_PUBLISHED_FLOOD` 或其他登录限制，不可作为对外发行产品的应用标识。长期使用应改为自己的应用配置：先备份，将受保护客户端 JSON 中 `api_id`、`api_hash` 改为自己申请的值、`test_only` 设为 false；已经加密保存到账号内的配置须通过已有登录配置入口更新，或在未登录的新账号槽位使用新配置。不要删除已授权 Session 来“修复”限流，也不要反复自动重试。

依据：[Telegram QR 协议](https://core.telegram.org/api/qr-login)、[Telethon QR 登录](https://docs.telethon.dev/en/stable/modules/client.html#telethon.client.auth.AuthMethods.qr_login)、[官方测试样例的使用限制](https://core.telegram.org/api/obtaining_api_id)、[Telegram Desktop 配置来源](https://github.com/telegramdesktop/tdesktop/blob/dev/Telegram/SourceFiles/config.h)。

## 管理与更新

### 多账号与结束会话

点击页面顶栏的“管理账号”（手机也显示此入口），或侧栏的“账号管理”：

1. “添加账号”填写便于识别的名称，创建后进入该账号的扫码页。应用配置从当前账号复制并加密保存，不复制登录 Session；无需重复填写已配置的 API。
2. 各账号分别用手机扫码；有两步验证时输入该账号的密码。顶栏下拉框或账号卡片可切换，切换不撤销登录，原账号的后台任务仍使用原账号执行。重命名只修改本地备注。
3. “结束会话”确认后调用 Telegram `log_out`，撤销本应用对应的登录，再清理该账号的本地 Session。手机与其他设备不受影响，已下载文件保留。排队下载改为暂停、排队发送取消；存在正在下载/发送的任务时拒绝退出，请先暂停/取消。
4. “移除账号”先完成同样的退出，再删除账号入口；至少保留一个账号入口。删除当前账号后切换至剩余账号。退出后台只清除管理员网页 Cookie。

账号卡片检查实际授权状态；文件存在不等于已经登录，网络异常显示“暂时无法确认”。退出接口按明确的账号 ID 执行，不依赖可变的当前账号；手机号登录和两步验证也固定到发起登录的账号。退出失败时不删除 Session、不移除账号，不返回成功，保留后可重试。服务重启后未加载的 Session 也会先连接 Telegram 再撤销，而不是只删除文件。

账号管理 API（都要求管理员登录）：`GET/POST /api/accounts`、`PATCH/DELETE /api/accounts/{id}`、`POST /api/accounts/{id}/activate`、`POST /api/accounts/{id}/logout`。兼容旧 `/api/telegram/logout`，同样执行真实退出。参考 [Telethon 退出定义](https://docs.telethon.dev/en/stable/modules/client.html#telethon.client.auth.AuthMethods.log_out)。

本次版本把下载/媒体唯一键从 `(channel_id,message_id)` 迁移至 `(account_id,channel_id,message_id)`，避免两个账号下载同一消息时混用记录；文件目录原本已按账号分开。启动时在事务中迁移，保留记录 ID、路径、自增序列和外键，重复启动不重复迁移。**更新前必须备份；迁移后若要回到旧版本，按下述配套数据恢复步骤回滚，不直接切换旧镜像。** 本地媒体库是同一管理员共享的已下载文件列表，不属于 Telegram 云端会话。

所有操作先进入实际项目目录，避免在其他服务目录运行命令：

```bash
cd /data/workspace/tg-web-archive
bash scripts/instabox.sh status
bash scripts/instabox.sh logs app
bash scripts/instabox.sh logs nginx
bash scripts/instabox.sh restart
bash scripts/instabox.sh backup
```

备份会仅停止本项目容器，打包 `.env` 和整个 `data/`（SQLite、Session、客户端配置、媒体与 `.part` 文件），权限 600，随后恢复本项目并等待健康。备份失败也会尝试重新启动。备份可能包含密码哈希、密钥和登录 Session，需安全保管；媒体多时检查剩余空间并迁移备份，不要公开上传。

更新前记录旧提交、镜像标签并完成备份。工作树存在其他修改时先查明用途，不使用 `reset --hard` 或 `clean` 清除：

```bash
git status --short
git rev-parse HEAD
docker compose -p tg-web-archive -f docker-compose.instabox.yml images
bash scripts/instabox.sh backup
git fetch origin
git merge --ff-only origin/main
bash scripts/instabox.sh deploy
```

重复部署保留 `.env`、加密密钥和数据。镜像使用提交短哈希命名；不要在未备份时清理旧镜像。Nginx 使用官方 `stable-alpine`，重拉可能升级版本；需严格复现时，先记录 `docker image inspect nginx:stable-alpine --format '{{json .RepoDigests}}'`，再使用该不可变摘要。

## 回滚与恢复

没有数据库不兼容变更时，先备份当前数据、确认旧镜像仍在，使用旧镜像标签短暂回退：

```bash
previous_tag=<更新前记录的镜像标签>
IMAGE_TAG="$previous_tag" docker compose -p tg-web-archive \
  -f docker-compose.instabox.yml up -d --wait --wait-timeout 180
```

该命令只切换运行镜像。持续回退时，应在工作树干净且已经备份的前提下切换到对应代码提交，再执行 `bash scripts/instabox.sh deploy`，它会同步 `.env` 中的标签。

涉及不兼容结构迁移时，必须同时恢复该版本配套的 `.env`、`data/` 和客户端配置。先停止**本项目**，将当前数据安全移至同项目的带日期恢复目录，不覆盖或直接删除；检查可信备份只包含 `.env`、`data/`，没有绝对路径或 `..`，再恢复、核对 UID/GID 与权限、切换对应代码并启动验收。旧备份可能丢失新媒体或最新授权，恢复前保留当前备份。不要执行 `docker compose down -v`、全局 Docker prune 或删除其他项目目录。

## 自动化验证

在临时容器中挂载源码和测试，**不挂载生产 `.env` 或 `data/`**：

```bash
docker run --rm -e PYTHONPATH=/workspace \
  -v "$PWD/app:/workspace/app:ro" \
  -v "$PWD/tests:/workspace/tests:ro" \
  -v "$PWD/scripts:/workspace/scripts:ro" \
  -v "$PWD/requirements.txt:/workspace/requirements.txt:ro" \
  -w /workspace \
  "$(docker compose -p tg-web-archive -f docker-compose.instabox.yml images -q app)" \
  sh -c 'pip install --quiet pytest httpx pip-audit && pytest -q -p no:cacheprovider && python tests/api_smoke.py && pip-audit -r requirements.txt'
```

2026-10-22 融合 `fix/reliability-20261022` 分支后通过 43 项测试、API 冒烟和依赖审计（0 已知漏洞）。测试涵盖账号创建、配置加密与隔离、切换、重命名、真实授权状态判定、重启后加载 Session 撤销、失败保留 Session、仅暂停目标账号队列、运行中任务保护、删除首账号的回退，以及旧数据库迁移的 ID/自增序列/外键/重复启动。原有队列去重、暂停续传与重启恢复、SQLite 并发、初始化不覆盖密钥、二维码刷新/取消/两步验证分支/错误脱敏/等待上限也通过。API 测试另验证鉴权、修改密码后旧会话失效、凭据查看保护、媒体删除、目录穿越拦截及 Range。

本次融合还验证了不完整文件禁止入库、取消暂停/失败/排队任务实际清理 `.part`、断点续传只为剩余字节预留空间。额外修复了传输后读取媒体信息期间的取消/暂停/服务停止：先处理 `.part`，再在任务锁内发布完整文件和入库；中途停止仍能保留可续传文件。真实 ffprobe/ffmpeg 对 `.part` 文件的元数据和缩略图读取也通过。无效的继续或重试请求返回 409，不再清除仍在等待执行的暂停/取消标记。Range 在 X-Accel 转发前校验，直传与 Nginx 加速两种路径均拒绝畸形或超界请求并禁止缓存错误。

可靠性融合本身没有新增数据库结构变更，融合前的多账号版本 `dd9a536` 已使用相同账号唯一键，可按同结构镜像回滚方法退回。更早、尚未迁移账号唯一键的版本仍须恢复配套数据。

融合保留了可靠性分支的历史 [VALIDATION_20261022.md](../VALIDATION_20261022.md)，其中另一实例的测速与备份路径不适用于此 InstaBox；不能混用两份文档的服务器信息。

`tests/accounts_ui_server.py` 是**仅供隔离测试的服务**，强制使用临时数据和模拟 Telegram，不可用于真实部署或发布公网。只将源码与 tests 只读挂载到一次性容器，绑定空闲回环测试端口，不挂生产数据、`.env` 或客户端配置；从测试镜像运行 `python tests/accounts_ui_server.py`。安装 Playwright 后，以 `TEST_URL=http://127.0.0.1:<测试端口> PLAYWRIGHT_MODULE=<playwright/index.mjs的绝对路径> node tests/accounts_ui.mjs` 执行，Chromium 使用 `/usr/bin/chromium`、headless。测试截图写入私有 `/data/workspace/tg-web-archive-e2e/`，该目录须事先创建。

无头浏览器隔离验收覆盖：添加第二账号并模拟扫码/两步验证、两个账号保持登录、重命名、取消退出、网络失败保留并重试、只退出目标账号、移除账号后回退、页面刷新及 390/320 像素手机布局。模拟通过不等于第二个真实 Telegram 账号已登录或已实测真实会话撤销。线上验收保留用户刚完成的真实授权，禁止为了测试把该账号退出。

本实例已另行实测：公网 HTTPS 和安全 Cookie、未登录接口与 internal 媒体路径拦截、真实 Telegram 二维码生成和过期刷新、二维码取消、桌面和 390×844 手机无头 Chromium、页面刷新后的管理会话保留。两步验证页面由模拟服务状态验证，不能等同于真实账号两步验证成功。

媒体与持久化验收曾使用本地合成的 1 秒 MP4、暂停任务 `.part` 和加密配置探针；检查 Nginx X-Accel 的 206 分段响应、容器重启后文件/数据库/解密/暂停状态保留，随后清理测试数据。停机一致备份已在独立目录解包验证 SQLite 完整性和配套密钥解密，没有启动第二个真实 Telegram 实例。用户现已完成真实扫码授权；本次账号迭代前再次备份，发布后检查同一账号授权仍在。第二个真实账号、真实退出撤销、真实下载、断网续传和上传仍需使用相应账号分别验收，不能根据模拟报告宣称成功。

## 接手检查

1. 从操作者授权的受保护文件取得当前机器连接信息和管理密码，先核对机器身份、现有服务、端口和 Git 工作树。
2. 读取本说明、现有 `.env` 和数据目录的存在性；只输出配置摘要或权限，不输出秘密。
3. 先检查现有实例的健康和公网入口，区分普通 Compose 与 InstaBox 专用文件。
4. 验证管理登录、二维码生成和手机确认；未完成手机确认就明确标注 Telegram 未授权，不依据历史报告宣称下载或上传已通过。
5. 更新前备份、保留旧镜像，完成必要测试、重启持久化、公网验收后再推送交付。保活与监控是既有独立服务，不随本项目更新。

排障：二维码生成 502 时检查 Telegram 出站网络和测试样例是否限流；登录 429 时等候限速窗口；本地 HTTP 登录后仍未登录通常是 Secure Cookie 预期行为；权限错误检查 `APP_UID/APP_GID` 和本项目数据所有权；数据库存在而密钥缺失时恢复配套备份，禁止生成新密钥覆盖。
