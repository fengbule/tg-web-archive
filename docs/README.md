# 技术文档

[项目首页](../README.md) · [使用指南](USER_GUIDE.md) · [运维指南](../scripts/README-小白运维.md)

## 按需查阅

| 主题 | 文档 |
| --- | --- |
| InstaBox 部署 | [独立安装、更新与回滚](INSTABOX.md) |
| Telegram 客户端 | [会话、消息、频道管理与测试](TELEGRAM_CLIENT_20261030.md) |
| 下载速度 | [并行连接池](DOWNLOAD_CONNECTIONS_20261023.md)、[网络调优实验](NETWORK_TUNING_20261023.md) |
| 播放体验 | [原画播放器](ORIGINAL_PLAYER_20261023.md)、[触控操作](PLAYER_CONTROLS_20261024.md)、[方向锁与选集](PLAYER_LOCK_PLAYLIST_20261024.md) |
| 媒体浏览 | [频道封面与下载状态](CATALOG_DOWNLOAD_20261023.md)、[相册封面](ALBUM_COVERS_20261025.md)、[标题说明](TG_COVERS_TITLES_20261025.md) |
| 收藏与布局 | [视频收藏](FAVORITES_20261024.md)、[手机 / 平板 / 电脑布局](CLIENT_VIEWS_20261025.md) |
| 账号迁移 | [加密账号备份与切片预览](THEME_BACKUP_PREVIEW_20261023.md) |
| 访问控制 | [密码保护、封面同步与缓冲进度](BUFFER_COVER_AUTH_20261025.md) |

## 开发入口

| 路径 | 用途 |
| --- | --- |
| `app/main.py` | Web API、认证与媒体管理 |
| `app/telegram_service.py` | Telegram 登录与消息服务 |
| `app/downloader.py` | 下载队列、恢复与磁盘保护 |
| `app/transcoder.py` | 无损封装、原编码分片与可选 480P |
| `app/outbox.py` | 后台媒体发送队列 |
| `app/static/` | 网页界面与播放器 |
| `tests/` | 单元、API 与无头浏览器测试 |

## 历史记录

带日期的文档保留当时的部署、实验和验收结果，不代表所有实例的当前状态。当前播放器默认原画，缓冲不会自动降画质；画质增强功能已移除，见 [移除说明](REMOVED_ENHANCEMENT_20261026.md)。

历史部署记录见 [VPS 运维记录](VPS-618HK.md)、[升级记录](UPGRADE_20261023.md) 与 [验收记录](../VALIDATION_20261023.md)。真实凭据、Session、数据库与日志不得放入仓库。
