#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_ROOT="${DATA_ROOT:-/data/telegram-video-manager}"
BACKUP_DIR="${BACKUP_DIR:-/data/telegram-video-manager-backups}"
cd "$PROJECT_DIR"

green(){ printf '\033[32m%s\033[0m\n' "$*"; }
yellow(){ printf '\033[33m%s\033[0m\n' "$*"; }
die(){ printf '\033[31m错误：%s\033[0m\n' "$*" >&2; exit 1; }
need_root(){ [ "$(id -u)" -eq 0 ] || die "请使用 sudo 运行此操作"; }
need_docker(){ command -v docker >/dev/null || die "未安装 Docker，请先安装 Docker Engine"; docker compose version >/dev/null 2>&1 || die "未安装 Docker Compose 插件"; }

make_env(){
  [ -f .env ] && return
  command -v python3 >/dev/null || die "需要 Python 3 来安全生成配置"
  printf '请设置管理员密码（至少12位，不会明文保存）：'
  read -rs password; printf '\n'
  [ "${#password}" -ge 12 ] || die "密码长度不足12位"
  printf '请再次输入管理员密码：'
  read -rs password2; printf '\n'
  [ "$password" = "$password2" ] || die "两次密码不一致"
  ADMIN_PASSWORD="$password" python3 - <<'PY' > .env
import os,base64,hashlib,secrets
p=os.environ.pop('ADMIN_PASSWORD').encode(); salt=secrets.token_bytes(18)
h=hashlib.pbkdf2_hmac('sha256',p,salt,600_000)
print('ADMIN_PASSWORD_PBKDF2='+base64.urlsafe_b64encode(salt).decode()+':'+base64.urlsafe_b64encode(h).decode())
print('SESSION_SECRET='+secrets.token_hex(32))
print('CONFIG_ENCRYPTION_KEY='+base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())
print('DATA_ROOT=/data/telegram-video-manager')
print('MIN_FREE_GB=10')
print('DOWNLOAD_CONCURRENCY=2')
print('COOKIE_SECURE=false')
print('APP_VERSION=1.1.0')
PY
  chmod 600 .env
}

install_app(){
  need_root; need_docker
  install -d -m 700 "$DATA_ROOT"/{temp,database,session,config,thumbnails}
  install -d -m 755 "$DATA_ROOT/media"
  make_env
  docker compose up -d --build
  green "安装完成。访问：http://服务器IP:8080"
  docker compose ps
}
update_app(){ need_root; need_docker; [ -f .env ] || die "尚未安装，请先执行 install"; docker compose build --pull; docker compose up -d; green "更新完成"; }
status_app(){ need_docker; docker compose ps; printf '\n健康检查：'; curl -fsS http://127.0.0.1:8080/health && printf '\n'; df -h "$DATA_ROOT"; }
logs_app(){ need_docker; docker compose logs --tail=200 -f app; }
backup_app(){
  need_root; need_docker; install -d -m 700 "$BACKUP_DIR"; stamp="$(date +%Y%m%d-%H%M%S)"; file="$BACKUP_DIR/tvm-$stamp.tar.gz"
  yellow "正在短暂停止服务以生成一致备份…"; docker compose stop
  trap 'docker compose start >/dev/null 2>&1 || true' EXIT
  tar -C "$(dirname "$DATA_ROOT")" -czf "$file" "$(basename "$DATA_ROOT")"
  cp -p .env "$BACKUP_DIR/tvm-$stamp.env"; chmod 600 "$file" "$BACKUP_DIR/tvm-$stamp.env"; docker compose start; trap - EXIT
  green "备份完成：$file"
}
reset_admin_password(){
  need_root; need_docker; [ -f .env ] || die "尚未安装，找不到 .env"
  command -v python3 >/dev/null || die "需要 Python 3 来安全重置密码"
  printf '请输入新的管理员密码（至少12位）：'; read -rs password; printf '\n'
  [ "${#password}" -ge 12 ] || die "密码长度不足12位"
  printf '请再次输入新的管理员密码：'; read -rs password2; printf '\n'
  [ "$password" = "$password2" ] || die "两次密码不一致"
  ADMIN_PASSWORD="$password" PROJECT_ENV="$PROJECT_DIR/.env" APP_DB="$DATA_ROOT/database/app.db" python3 - <<'PY'
import os,base64,hashlib,secrets,sqlite3
env_path=os.environ['PROJECT_ENV']; password=os.environ.pop('ADMIN_PASSWORD').encode()
salt=secrets.token_bytes(18); digest=hashlib.pbkdf2_hmac('sha256',password,salt,600_000)
encoded=base64.urlsafe_b64encode(salt).decode()+':'+base64.urlsafe_b64encode(digest).decode()
lines=open(env_path,encoding='utf-8').read().splitlines()
lines=[('ADMIN_PASSWORD_PBKDF2='+encoded) if x.startswith('ADMIN_PASSWORD_PBKDF2=') else x for x in lines]
if not any(x.startswith('ADMIN_PASSWORD_PBKDF2=') for x in lines): lines.append('ADMIN_PASSWORD_PBKDF2='+encoded)
open(env_path,'w',encoding='utf-8').write('\n'.join(lines)+'\n')
db_path=os.environ['APP_DB']
if os.path.exists(db_path):
    c=sqlite3.connect(db_path)
    c.execute("DELETE FROM config WHERE key='admin_password_pbkdf2'")
    c.execute("INSERT OR REPLACE INTO config(key,value) VALUES('admin_auth_version',?)",(secrets.token_urlsafe(24),))
    c.commit(); c.close()
PY
  chmod 600 .env; docker compose up -d --force-recreate
  green "管理员密码已重置，所有旧登录已失效。请使用新密码登录。"
}
uninstall_app(){
  need_root; need_docker; docker compose down --remove-orphans
  green "程序容器已卸载。视频和数据库仍安全保留在 $DATA_ROOT"
  if [ "${1:-}" = "--purge-data" ]; then
    yellow "危险：这会永久删除全部视频、数据库和 Telegram Session。"
    printf '请输入 永久删除全部数据 以确认：'; read -r confirm
    [ "$confirm" = "永久删除全部数据" ] || die "确认文字不匹配，已取消"
    case "$DATA_ROOT" in /data/telegram-video-manager) rm -rf --one-file-system "$DATA_ROOT";; *) die "数据目录异常，拒绝删除";; esac
    rm -f .env; green "项目数据已永久删除"
  fi
}
menu(){
  printf '\nTelegram 视频管理器\n1) 安装/启动\n2) 更新\n3) 查看状态\n4) 查看日志\n5) 备份\n6) 重置管理员密码\n7) 卸载（保留数据）\n0) 退出\n请选择：'
  read -r n; case "$n" in 1) install_app;;2) update_app;;3) status_app;;4) logs_app;;5) backup_app;;6) reset_admin_password;;7) uninstall_app;;0) exit 0;;*) die "无效选择";;esac
}

case "${1:-menu}" in
  install) install_app;; update) update_app;; status) status_app;; logs) logs_app;; backup) backup_app;; reset-password) reset_admin_password;; uninstall) uninstall_app "${2:-}";; menu) menu;; *) die "用法：$0 {install|update|status|logs|backup|reset-password|uninstall [--purge-data]}";;
esac
