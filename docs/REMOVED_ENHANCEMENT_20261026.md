# 移除画质增强

按用户要求，完整移除实时滤镜、自适应锐化、局部对比度、强度设置、左右分屏、按住对比、离线增强入口及后台生成实现。播放器恢复直接显示视频，默认原画；原画 HLS/Range、预览切片、快进、暂停按钮、横屏/方向锁定、上下集、收藏、本机下载、明暗主题与多账号保持原有行为。

前端删除 4 个增强 JS/CSS 文件与全部引用，更新 `premium.js?v=17`；加载时只清除两个废弃增强偏好，不清除登录、播放进度或其他设置。服务器删除增强模块、生成/查询/删除接口、转码 worker 分支；旧增强接口返回 404/405，`quality=enhanced` 或其他未知画质返回 400，不会启动任务或冒充原画下载。

已有数据库中的废弃字段保留，不做 DROP/重建表，不删除或改写媒体和账号；全新数据库不再创建增强字段。旧 queued/processing 记录不会恢复或被 worker 执行。既有手动生成的衍生文件不会批量删除；只有用户日后明确删除对应整条媒体时，兼容清理代码才会清理其旧衍生文件。此部署不修改原视频、Session、API 凭据、密码、下载、收藏或其他服务。

## 部署与管理

更新前已确认机器身份、资源、容器与端口，并创建受保护的 SQLite/Session/配置备份：

- VPS：`/root/backups/tg-web-archive-unenhanced-20261026T045828Z`。
- InstaBox：`/data/workspace/tg-web-archive/backups/tg-web-archive-unenhanced-20261026T045826Z`。

凭据继续从原有受保护文件读取，具体位置与私有校验报告由操作者 `output/tg-web-archive/部署交接.md` 记录；不要将 `.env`、数据目录、日志、凭据和用户素材提交仓库。

```sh
# VPS
cd /opt/telegram-video-manager
git fetch origin && git merge --ff-only origin/main
docker compose -p telegram-video-manager build app
docker compose -p telegram-video-manager up -d --no-deps --force-recreate --wait app
docker compose -p telegram-video-manager restart nginx
curl -fsS http://127.0.0.1:8080/health

# InstaBox；仅更新原 .env 的 IMAGE_TAG，保留其他配置
cd /data/workspace/tg-web-archive
git fetch origin && git merge --ff-only origin/main
export IMAGE_TAG="$(git rev-parse --short=12 HEAD)"
docker compose -p tg-web-archive -f docker-compose.instabox.yml build app
docker compose -p tg-web-archive -f docker-compose.instabox.yml up -d --no-deps --force-recreate --wait app
docker compose -p tg-web-archive -f docker-compose.instabox.yml restart nginx
curl -fsS http://127.0.0.1:8081/health
```

更新不会清理卷、停其他项目或修改保活。保持原有数据目录与 Compose 项目名，禁止 `down -v`。无需恢复旧数据库，避免覆盖期间的新下载。历史增强文档只留作归档，不应按其步骤重新启用该功能。

若本次更新有其他业务回归、需要回退同时保持无增强，可在对应项目干净工作树执行 `git switch --detach acc0958`，从该原画基础版本重新构建并只替换本项目 app/nginx；InstaBox 使用独立 IMAGE_TAG 并写回原 `.env`。本次没有破坏性数据库迁移，保留现有 DB/Session/视频即可。更新前镜像只是诊断备份，直接恢复会重新带回增强，不作为满足当前需求的常规回退。

## 验证

`tests/test_removed_enhancement.py` 模拟旧数据库 queued/processing 任务，检查重启后不会恢复或执行、源文件不变。API 冒烟检查旧接口关闭、旧画质参数拒绝、原画 Range/下载仍可用；`tests/enhancement_removed_ui.mjs` 从旧增强偏好启动，检查偏好清理、菜单和播放器无增强入口/画布/滤镜/后台请求、旧资源 404、原画播放/拖动和明暗主题布局。其他播放器、锁屏选集、封面及 API 检查使用独立合成数据，不写生产库。
