#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

ENV_FILE=".env.docker"
command -v docker >/dev/null || { echo "Docker не установлен. См. DEPLOY.md, шаг 2." >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "Нужен плагин Docker Compose v2 (docker compose)." >&2; exit 1; }

if [ -f "$ENV_FILE" ] && [ "${1:-}" != "--force" ]; then
  echo "Файл $ENV_FILE уже есть — настройка уже выполнена." >&2
  echo "Запуск/обновление: bash docker/update.sh   (перезаписать настройки: bash docker/setup.sh --force)" >&2
  exit 1
fi

rand() { head -c "$1" /dev/urandom | od -An -tx1 | tr -d ' \n'; }

read -r -p "Домен для CRM (например crm.example.ru; пусто — без домена, по http://IP:8000): " domain
read -r -p "Email первого администратора [admin@example.com]: " admin_email
admin_email="${admin_email:-admin@example.com}"
read -r -p "Название CRM [Universal CRM]: " app_name
app_name="${app_name:-Universal CRM}"
read -r -p "Часовой пояс [Europe/Moscow]: " tz
tz="${tz:-Europe/Moscow}"

admin_password="$(rand 9)"

if [ -n "$domain" ]; then
  bind="127.0.0.1"; secure="true"; proxy="true"
else
  bind="0.0.0.0";   secure="false"; proxy="false"
fi

umask 077
cat > "$ENV_FILE" <<EOF
POSTGRES_PASSWORD=$(rand 24)
SECRET_KEY=$(rand 32)
FIRST_ADMIN_EMAIL=$admin_email
FIRST_ADMIN_PASSWORD=$admin_password
FIRST_ADMIN_NAME=Администратор
APP_NAME=$app_name
APP_TIMEZONE=$tz
APP_BIND=$bind
APP_PORT=8000
DOMAIN=${domain:-crm.example.com}
AUTH_COOKIE_SECURE=$secure
TRUST_PROXY_HEADERS=$proxy
BACKUP_KEEP_DAYS=14
BACKUP_INTERVAL_HOURS=24
IMPORT_MAX_ROWS=5000
IMPORT_MAX_FILE_MB=5
EOF
echo "Создан $ENV_FILE (права только для владельца)."

profile=()
[ -n "$domain" ] && profile=(--profile https)
docker compose --env-file "$ENV_FILE" "${profile[@]}" up -d --build

echo "Жду, пока приложение запустится..."
ok=""
for _ in $(seq 1 40); do
  if curl -fsS "http://127.0.0.1:8000/health" >/dev/null 2>&1; then ok=1; break; fi
  sleep 3
done
[ -n "$ok" ] || { echo "Приложение не ответило. Смотрите: docker compose --env-file $ENV_FILE logs app" >&2; exit 1; }

echo
echo "============================================================"
echo " CRM запущена."
if [ -n "$domain" ]; then
  echo " Адрес:   https://$domain   (сертификат выпускается при первом обращении, до минуты)"
else
  echo " Адрес:   http://IP-СЕРВЕРА:8000"
fi
echo " Логин:   $admin_email"
echo " Пароль:  $admin_password"
echo " Запишите пароль и смените его после входа. Он же лежит в $ENV_FILE."
echo "============================================================"
