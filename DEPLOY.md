# Развёртывание на сервере: пошагово

Всё готово заранее: когда появится сервер, нужно выполнить шаги ниже. Ничего в коде менять не надо.

## 0. Что понадобится
- **Сервер (VPS)**: Ubuntu 24.04 LTS (подойдёт 22.04 / Debian 12), 2 ГБ памяти, 20 ГБ диска, публичный IP.
  Этого хватает на десятки пользователей. Подойдёт любой хостинг (Timeweb, Selectel, Hetzner и т. п.).
- **Домен** (желательно): без него CRM работает по `http://IP:8000` без шифрования — годится только для проверки.
  Создайте у регистратора **A-запись** `crm.ваш-домен.ru` → IP сервера (до начала шага 4).

## 1. Подключитесь и защитите сервер
```bash
ssh root@IP-СЕРВЕРА
apt update && apt -y upgrade
ufw allow OpenSSH && ufw allow 80 && ufw allow 443/tcp && ufw allow 443/udp   # для режима без домена: ufw allow 8000
ufw --force enable
```
Рекомендуется вход по SSH-ключу и отключённый вход root по паролю (инструкция вашего хостинга).

## 2. Установите Docker
```bash
curl -fsSL https://get.docker.com | sh
docker compose version      # должна показать версию v2.x
```

## 3. Загрузите проект
Через git (удобнее для обновлений):
```bash
apt -y install git
git clone <адрес-вашего-репозитория> /opt/crm && cd /opt/crm
```
Или с вашего компьютера (PowerShell): `scp -r "C:\Users\serge\Projects\Universal CRM" root@IP-СЕРВЕРА:/opt/crm`
(папки `.venv`, `.env.docker`, `backups` копировать не нужно).

## 4. Запустите одной командой
```bash
cd /opt/crm
bash docker/setup.sh
```
Скрипт спросит домен, email администратора, название и часовой пояс, сам создаст `.env.docker` со
случайными паролями, поднимет базу, приложение, резервное копирование и (если указан домен) HTTPS,
и в конце покажет адрес, логин и пароль. Пароль сразу смените в профиле.

## 5. Проверьте
- Откройте адрес в браузере, войдите, создайте тестового клиента и сделку.
- `docker compose --env-file .env.docker ps` — все сервисы `Up` / `healthy`.
- `ls backups` — появился файл `crm_….dump`.
- Перезагрузите сервер (`reboot`): всё должно подняться само (`restart: unless-stopped`).

## 6. Копии вне сервера (обязательно)
Копии в `backups/` лежат на том же диске, что и база. Настройте копирование наружу, например с вашего
компьютера раз в день (Планировщик заданий Windows, PowerShell):
```powershell
scp -r root@IP-СЕРВЕРА:/opt/crm/backups "D:\crm-backups"
```
или на сервере через `rclone` в облако. **Один раз проверьте восстановление** на тестовой копии:
`bash docker/restore.sh backups/crm_….dump` (текущие данные заменяются).

## 7. Обновление версии
Загрузите новые файлы (`git pull` или `scp`) и выполните:
```bash
bash docker/update.sh
```
Скрипт сначала сохраняет копию базы `backups/crm_before_update_….dump`, затем пересобирает контейнеры;
миграции базы применяются сами.

## Если что-то не так
| Симптом | Что делать |
|---|---|
| Сайт по домену не открывается | A-запись должна указывать на IP сервера; порты 80/443 открыты; `docker compose --env-file .env.docker logs caddy` |
| «Не удалось применить миграции» | `docker compose --env-file .env.docker logs app`; данные не затрагиваются, пришлите журнал |
| Забыли пароль администратора | `docker compose --env-file .env.docker exec app python -m app.cli reset-password --email a@b.ru` |
| Нужно откатить версию | `git checkout <прежний-коммит>`, затем восстановить базу из `backups/crm_before_update_….dump` через `docker/restore.sh` |

Все команды `docker compose` выполняйте с `--env-file .env.docker` (или один раз `export COMPOSE_ENV_FILES=.env.docker`).
