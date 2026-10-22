#!/usr/bin/env bash
# Only manages this checkout's InstaBox Compose project; never touches other services.
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PWD="$(pwd -P)"
compose=(docker compose -p tg-web-archive -f docker-compose.instabox.yml)
require_env() { [ -s .env ] || { echo 'Run init first.' >&2; exit 1; }; }
case "${1:-status}" in
  init)
    python3 scripts/init_instabox.py
    ;;
  deploy)
    require_env
    command -v instabox-port >/dev/null
    # Standardize data paths and keep secrets private; Nginx needs read access to media.
    install -d -m 700 data data/{temp,database,session,config,thumbnails}
    install -d -m 755 data/media
    chmod 600 .env
    export IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short=12 HEAD)}"
    "${compose[@]}" config --quiet
    "${compose[@]}" build --pull
    "${compose[@]}" up -d --wait --wait-timeout 180
    python3 - <<'PY'
from pathlib import Path
import subprocess, urllib.request
values=dict(line.split('=',1) for line in Path('.env').read_text().splitlines() if '=' in line and not line.startswith('#'))
port=values.get('HTTP_PORT','8081')
if not port.isdigit() or not 1024<=int(port)<=65535: raise SystemExit('Invalid HTTP_PORT')
with urllib.request.urlopen('http://127.0.0.1:'+port+'/health',timeout=10) as r:
    assert r.status==200
subprocess.run(['instabox-port','publish',port],check=True)
env=Path('.env')
lines=[line for line in env.read_text().splitlines() if not line.startswith('IMAGE_TAG=')]
import os, tempfile
lines.append('IMAGE_TAG='+os.environ['IMAGE_TAG'])
with tempfile.NamedTemporaryFile(mode='w',dir=env.parent,prefix='.env.deploy-',delete=False) as f:
    f.write('\n'.join(lines)+'\n'); f.flush(); os.fsync(f.fileno()); tmp=f.name
os.replace(tmp,env)
PY
    ;;
  status) require_env; "${compose[@]}" ps ;;
  logs) require_env; "${compose[@]}" logs --tail=100 "${2:-app}" ;;
  restart) require_env; "${compose[@]}" restart; "${compose[@]}" up -d --wait --wait-timeout 180 ;;
  backup)
    require_env
    umask 077
    install -d -m 700 backups
    backup="backups/tg-web-archive-$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
    "${compose[@]}" stop
    trap '"${compose[@]}" start >/dev/null' EXIT
    tar -czf "$backup" .env data
    chmod 600 "$backup"
    "${compose[@]}" start
    trap - EXIT
    "${compose[@]}" up -d --wait --wait-timeout 180
    printf 'Backup saved: %s\n' "$backup"
    ;;
  *) echo 'Usage: bash scripts/instabox.sh {init|deploy|status|logs [app|nginx]|restart|backup}' >&2; exit 1 ;;
esac
