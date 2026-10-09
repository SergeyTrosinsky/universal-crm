#!/bin/sh
KEEP="${BACKUP_KEEP_DAYS:-14}"
EVERY="${BACKUP_INTERVAL_HOURS:-24}"
mkdir -p /backups

backup() {
  stamp="$(date +%Y%m%d_%H%M%S)"
  tmp="/backups/.crm_${stamp}.tmp"
  out="/backups/crm_${stamp}.dump"
  if pg_dump --format=custom --file="$tmp" && pg_restore --list "$tmp" > /dev/null; then
    mv "$tmp" "$out"
    echo "[backup] Готово: $out ($(du -h "$out" | cut -f1))"
    find /backups -name 'crm_*.dump' -mtime "+${KEEP}" -print -delete | sed 's/^/[backup] Удалена старая копия: /'
  else
    rm -f "$tmp"
    echo "[backup] ОШИБКА: резервная копия не создана" >&2
  fi
}

echo "[backup] Копии каждые ${EVERY} ч, хранение ${KEEP} дн."
while true; do
  backup
  sleep "$((EVERY * 3600))"
done
