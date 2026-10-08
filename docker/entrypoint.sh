#!/bin/sh
# Запуск контейнера: сначала миграции базы, потом сервер.
set -e

echo "[crm] Применяю миграции базы данных..."
attempt=0
until alembic upgrade head; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 15 ]; then
    echo "[crm] Не удалось применить миграции: база недоступна или миграция завершилась ошибкой." >&2
    exit 1
  fi
  echo "[crm] Повторная попытка через 3 с ($attempt/15)..."
  sleep 3
done

echo "[crm] Запускаю сервер."
# Один процесс: счётчики неудачных входов хранятся в памяти и должны быть общими.
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips='*'
