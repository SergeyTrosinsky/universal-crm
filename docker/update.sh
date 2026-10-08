#!/usr/bin/env bash
# Обновление CRM на сервере: резервная копия -> новый код -> пересборка -> миграции (сами при старте).
#   bash docker/update.sh
set -euo pipefail
cd "$(dirname "$0")/.."
ENV_FILE="${ENV_FILE:-.env.docker}"
[ -f "$ENV_FILE" ] || { echo "Нет $ENV_FILE. Сначала: bash docker/setup.sh" >&2; exit 1; }

domain="$(grep -E '^DOMAIN=' "$ENV_FILE" | cut -d= -f2-)"
secure="$(grep -E '^AUTH_COOKIE_SECURE=' "$ENV_FILE" | cut -d= -f2-)"
profile=()
[ "$secure" = "true" ] && [ -n "$domain" ] && profile=(--profile https)
compose() { docker compose --env-file "$ENV_FILE" "${profile[@]}" "$@"; }

mkdir -p backups
stamp="$(date +%Y%m%d_%H%M%S)"
echo "Копия базы перед обновлением: backups/crm_before_update_$stamp.dump"
compose exec -T db pg_dump -U crm -d crm --format=custom > "backups/crm_before_update_$stamp.dump"

if [ -d .git ]; then
  git pull --ff-only
else
  echo "Папка не под git — считаю, что новые файлы уже загружены."
fi

compose up -d --build
docker image prune -f >/dev/null
echo "Готово. Проверка: curl http://127.0.0.1:8000/health"
