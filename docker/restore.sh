#!/usr/bin/env bash
# Восстановление базы из резервной копии (запускать на сервере, в папке проекта):
#   ./docker/restore.sh backups/crm_20261008_030000.dump
# ВНИМАНИЕ: текущие данные в базе будут заменены данными из копии.
set -euo pipefail

file="${1:-}"
if [ -z "$file" ] || [ ! -f "$file" ]; then
  echo "Использование: $0 <файл копии .dump>" >&2
  exit 1
fi

compose="docker compose --env-file ${ENV_FILE:-.env.docker}"

echo "Будет восстановлена база из: $file"
echo "Текущие данные CRM будут ЗАМЕНЕНЫ."
read -r -p "Продолжить? Введите yes: " answer
[ "$answer" = "yes" ] || { echo "Отменено."; exit 1; }

$compose stop app backup
$compose exec -T db psql -U crm -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS crm WITH (FORCE);" -c "CREATE DATABASE crm OWNER crm;"
$compose exec -T db pg_restore -U crm -d crm --no-owner --exit-on-error < "$file"
$compose start app backup
echo "Готово. База восстановлена."
