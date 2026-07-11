# 小白运维说明

进入项目目录后运行：

```bash
sudo bash scripts/manage.sh
```

会出现中文菜单，可直接选择安装、更新、状态、日志、备份或卸载。

- 普通“卸载”只删除容器，视频、数据库和 Telegram 登录状态仍保留。
- 只有显式执行 `sudo bash scripts/manage.sh uninstall --purge-data` 并再次输入中文确认文字，才会永久删除项目数据。
- 备份默认保存在 `/data/telegram-video-manager-backups`，包含数据压缩包和单独的加密配置文件。
- `.env`、备份配置文件和 `session` 目录都属于敏感数据，不要发送给别人。
