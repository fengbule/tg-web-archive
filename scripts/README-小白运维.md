# 运维指南

[返回项目首页](../README.md) · [使用指南](../docs/USER_GUIDE.md)

以下命令适用于默认 Linux / VPS 安装。InstaBox 使用独立 Compose 配置，请按 [InstaBox 部署指南](../docs/INSTABOX.md) 操作。

## 管理菜单

进入项目目录后运行：

```bash
sudo bash scripts/manage.sh
```

会出现中文菜单，可直接选择安装、更新、状态、日志、备份或卸载。

- 普通“卸载”只删除容器，视频、数据库和 Telegram 登录状态仍保留。
- 只有显式执行 `sudo bash scripts/manage.sh uninstall --purge-data` 并再次输入中文确认文字，才会永久删除项目数据。
- 备份默认保存在 `/data/telegram-video-manager-backups`，包含数据压缩包和单独的加密配置文件。
- `.env`、备份配置文件和 `session` 目录都属于敏感数据，不要发送给别人。

## 更新代码

在项目目录中先备份，再拉取代码并重新构建：

```bash
sudo bash scripts/manage.sh backup
git pull --ff-only
sudo bash scripts/manage.sh update
sudo bash scripts/manage.sh status
```

`manage.sh update` 只重新构建和启动，需要先用 Git 拉取新代码。有本地修改或分支冲突时，应先处理冲突再继续更新。

数据默认位于 `/data/telegram-video-manager`，更新会保留账号、媒体和下载临时文件。不要执行 `docker compose down -v` 或删除数据目录。

## 备份与恢复

```bash
sudo bash scripts/manage.sh backup
```

脚本会短暂停止服务，生成数据压缩包和配套 `.env` 文件，再启动服务。两份文件应一起安全保存；缺少原配置解密密钥可能无法读取 API 凭据。

恢复时先停止目标实例，再将数据包恢复到对应数据目录，并还原配套 `.env`、所有者与权限后启动。恢复会覆盖目标数据，应先为目标实例做备份。不要让原实例与恢复实例同时使用同一 Telegram 授权。

仅迁移 Telegram 账号时，可使用网页的加密账号导出 / 导入；视频与任务需要另外迁移。

## 状态、日志与密码

```bash
sudo bash scripts/manage.sh status
sudo bash scripts/manage.sh logs
sudo bash scripts/manage.sh reset-password
```

密码重置会要求输入两次新密码，使旧后台登录失效并重启容器，保留视频、数据库和 Telegram Session。排查日志时不要公开密码、Cookie、令牌或账号数据。

公网使用请配置 HTTPS，并在对应部署的 `.env` 中启用 `COOKIE_SECURE=true` 后重建应用容器。
