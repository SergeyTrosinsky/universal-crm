$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
Set-Location -LiteralPath $PSScriptRoot
$EnvFile = '.env.docker'
$env:GIT_PAGER = 'cat'
$env:LESS = 'FRX'

function Say([string]$t, [string]$c = 'Gray') { Write-Host $t -ForegroundColor $c }
function Pause-Menu { Write-Host ''; Read-Host 'Нажмите Enter, чтобы вернуться в меню' | Out-Null }
function Has-Cmd([string]$n) { [bool](Get-Command $n -ErrorAction SilentlyContinue) }
function Compose { & docker compose --env-file $EnvFile @args }

function Require-Git {
    if (-not (Has-Cmd git)) { Say 'Git не найден. Установите: https://git-scm.com/download/win' Red; return $false }
    if (-not (Test-Path '.git')) { Say 'Эта папка не является git-репозиторием.' Red; return $false }
    return $true
}
function Require-Docker {
    if (-not (Has-Cmd docker)) { Say 'Docker не найден.' Red; return $false }
    & docker info 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { Say 'Docker Desktop не запущен. Запустите его и повторите.' Yellow; return $false }
    if (-not (Test-Path $EnvFile)) { Say "Нет файла $EnvFile." Red; return $false }
    return $true
}
function Tree-Dirty { [bool](& git status --porcelain) }

function Show-Status {
    if (Require-Git) {
        Say '--- Git: изменения с последнего сохранения ---' Cyan
        & git status -sb
        Say "`nПоследняя сохранённая версия:" Cyan
        & git log -1 --format='%h  %ad  %s' --date=format:'%d.%m.%Y %H:%M'
        $ahead = (& git rev-list --count 'origin/main..HEAD' 2>$null)
        if ($LASTEXITCODE -eq 0 -and $ahead -ne '0') { Say "Не отправлено на GitHub версий: $ahead (пункт 3)." Yellow }
    }
    if (Require-Docker) {
        Say "`n--- Docker: контейнеры ---" Cyan
        Compose ps
    }
}

function Show-History {
    if (-not (Require-Git)) { return }
    Say 'Последние 20 версий (код — номер версии, дата, описание):' Cyan
    & git log -20 --format='%h  %ad  %s' --date=format:'%d.%m.%Y %H:%M'
}

function Save-Version {
    if (-not (Require-Git)) { return }
    & git add -A
    $bad = & git diff --cached --name-only | Select-String -Pattern '(^|/)\.env($|\.docker$)|\.db$|\.sqlite3?$|\.dump$|(^|/)backups/'
    if ($bad) {
        Say 'СТОП: в коммит попали файлы с секретами или данными:' Red
        $bad | ForEach-Object { Say "  $_" Red }
        & git reset -q
        Say 'Ничего не сохранено. Добавьте эти файлы в .gitignore.' Yellow
        return
    }
    if (-not (& git diff --cached --name-only)) { Say 'Новых изменений нет — сохранять нечего.' Yellow; return }
    & git diff --cached --stat
    $msg = Read-Host "`
Коротко опишите, что изменилось (пусто — отмена)"
    if ([string]::IsNullOrWhiteSpace($msg)) { & git reset -q; Say 'Отменено.' Yellow; return }
    & git commit -m $msg
    if ($LASTEXITCODE -eq 0) {
        Say 'Версия сохранена на этом компьютере (на GitHub не отправлена; отправка — пункт 3).' Green
    } else { Say 'Не удалось создать версию.' Red }
}

function Push-Github {
    if (-not (Require-Git)) { return }
    if (Tree-Dirty) { Say 'Есть несохранённые изменения — они на GitHub не попадут. Сначала пункт 2.' Yellow }
    $n = (& git rev-list --count 'origin/main..HEAD' 2>$null)
    if ($LASTEXITCODE -eq 0 -and $n -eq '0') { Say 'Все сохранённые версии уже на GitHub.' Green; return }
    Say "Отправляю на GitHub (версий к отправке: $n)..." Cyan
    & git push -u origin main
    if ($LASTEXITCODE -eq 0) { Say 'Готово: версии на GitHub.' Green } else { Say 'Отправка не удалась (см. выше). Версии сохранены локально.' Red }
}

function Rollback-Code {
    if (-not (Require-Git)) { return }
    if (Tree-Dirty) {
        Say 'Есть несохранённые изменения. Сначала сохраните их (пункт 2) или отмените вручную.' Yellow
        return
    }
    Show-History
    $hash = (Read-Host "`nНомер версии, к которой вернуться (пусто — отмена)").Trim()
    if (-not $hash) { Say 'Отменено.' Yellow; return }
    & git rev-parse --verify --quiet "$hash^{commit}" 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { Say 'Такой версии нет.' Red; return }
    Say "`nПроект будет приведён к состоянию версии $hash." Yellow
    Say 'История НЕ удаляется: откат записывается как новая версия, и к текущему состоянию можно вернуться так же.' Yellow
    if ((Read-Host 'Продолжить? Введите yes') -ne 'yes') { Say 'Отменено.' Yellow; return }
    & git revert --no-commit "$hash..HEAD"
    if ($LASTEXITCODE -ne 0) {
        & git revert --abort 2>&1 | Out-Null
        Say 'Автоматический откат не удался (конфликт). Ничего не изменено.' Red
        return
    }
    & git commit -m "Откат к версии $hash" | Out-Null
    Say "Готово: файлы возвращены к версии $hash. Чтобы отправить на GitHub — пункт 3." Green
    Say 'Чтобы применить к запущенному приложению: пункт «Пересобрать и обновить контейнеры».' Cyan
}

function Backup-Db([string]$Prefix = 'crm_manual') {
    if (-not (Require-Docker)) { return $null }
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $name = "${Prefix}_$stamp.dump"
    New-Item -ItemType Directory -Force -Path 'backups' | Out-Null
    Compose exec -T backup sh -c "pg_dump --format=custom --file=/backups/$name && pg_restore --list /backups/$name > /dev/null" | Out-Host
    if ($LASTEXITCODE -ne 0) { Say 'Копию создать не удалось (запущены ли контейнеры?).' Red; return $null }
    $f = Join-Path 'backups' $name
    Say ("Копия создана: {0} ({1:N0} КБ)" -f $f, ((Get-Item $f).Length / 1KB)) Green
    return $f
}

function Restore-Db {
    if (-not (Require-Docker)) { return }
    $files = @(Get-ChildItem backups -Filter '*.dump' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending)
    if (-not $files) { Say 'В папке backups нет копий.' Yellow; return }
    Say 'Доступные копии (сверху — самые новые):' Cyan
    for ($i = 0; $i -lt [Math]::Min($files.Count, 15); $i++) {
        Say ("  {0,2}) {1}   {2:dd.MM.yyyy HH:mm}   {3:N0} КБ" -f ($i + 1), $files[$i].Name, $files[$i].LastWriteTime, ($files[$i].Length / 1KB))
    }
    $n = Read-Host "`nНомер копии (пусто — отмена)"
    if (-not ($n -match '^\d+$') -or [int]$n -lt 1 -or [int]$n -gt [Math]::Min($files.Count, 15)) { Say 'Отменено.' Yellow; return }
    $file = $files[[int]$n - 1]
    Say "`nБаза будет ЗАМЕНЕНА данными из: $($file.Name)" Red
    Say 'Перед этим автоматически создаётся страховочная копия текущей базы.' Yellow
    if ((Read-Host 'Продолжить? Введите yes') -ne 'yes') { Say 'Отменено.' Yellow; return }
    if (-not (Backup-Db)) { Say 'Страховочная копия не создана — восстановление остановлено.' Red; return }
    Compose stop app backup
    Compose cp $file.FullName db:/tmp/restore.dump
    Compose exec -T db psql -U crm -d postgres -v ON_ERROR_STOP=1 -c 'DROP DATABASE IF EXISTS crm WITH (FORCE);' -c 'CREATE DATABASE crm OWNER crm;'
    Compose exec -T db pg_restore -U crm -d crm --no-owner --exit-on-error /tmp/restore.dump
    $ok = ($LASTEXITCODE -eq 0)
    Compose exec -T db rm -f /tmp/restore.dump
    Compose start app backup
    if ($ok) { Say 'Готово: база восстановлена.' Green } else { Say 'Ошибка восстановления. Страховочная копия лежит в backups\ (crm_manual_*).' Red }
}

function Load-Demo {
    if (-not (Require-Docker)) { return }
    Say 'Демо-сценарий «Континент» ЗАМЕНИТ все данные CRM: пользователей, клиентов, сделки, задачи, поля, шаблоны.' Red
    Say 'Перед этим будет создана копия текущей базы (crm_before_demo_*.dump), из неё можно вернуться пунктом 7.' Yellow
    if ((Read-Host 'Продолжить? Введите yes') -ne 'yes') { Say 'Отменено.' Yellow; return }
    $vin = (Read-Host 'Сразу создать поля «VIN» и «Госномер»? (для скриншотов; для записи видео — нет) [y/N]').Trim().ToLower()
    if (-not (Backup-Db 'crm_before_demo')) { Say 'Копия не создана — загрузка демо остановлена.' Red; return }
    $extra = @()
    if ($vin -eq 'y') { $extra += '--with-vin' }
    Compose exec -T app python -m app.cli seed-showcase --yes @extra
    if ($LASTEXITCODE -eq 0) { Say "`nГотово. Откройте CRM и войдите под director@kontinent.demo (пароль выше). Сценарий съёмки: DEMO_SCRIPT.md" Green }
    else { Say 'Загрузка демо не удалась (см. вывод выше). Данные можно вернуть пунктом 7.' Red }
}

function Rebuild {
    if (Require-Docker) { Compose up -d --build; if ($LASTEXITCODE -eq 0) { Say 'Контейнеры обновлены (миграции применились при старте).' Green } }
}
function Stop-All { if (Require-Docker) { Compose stop; Say 'Остановлено. Данные сохранены.' Green } }
function Start-All { if (Require-Docker) { Compose up -d } }
function Show-Logs { if (Require-Docker) { Say 'Последние строки журнала приложения:' Cyan; Compose logs --tail 60 app } }
function Run-Tests {
    $py = if (Test-Path 'venv\Scripts\python.exe') { 'venv\Scripts\python.exe' } else { 'python' }
    & $py -m pytest -q
}

while ($true) {
    Clear-Host
    Say '=============== Universal CRM — администрирование ===============' Cyan
    Say ' Версии кода (git / GitHub)'
    Say '   1) Состояние: что изменилось, какие контейнеры работают'
    Say '   2) Сохранить версию (только на этом компьютере)'
    Say '   3) Отправить сохранённые версии на GitHub'
    Say '   4) История версий'
    Say '   5) Откатить код к прошлой версии'
    Say ' База данных'
    Say '   6) Сделать резервную копию базы сейчас'
    Say '   7) Восстановить базу из копии'
    Say ' Приложение'
    Say '   8) Запустить контейнеры      9) Остановить контейнеры'
    Say '  10) Пересобрать и обновить контейнеры (после изменения кода)'
    Say '  11) Журнал приложения        12) Запустить тесты'
    Say ' Демонстрация'
    Say '  13) Загрузить демо-сценарий «Континент» (заменит данные, с копией перед этим)'
    Say '   0) Выход'
    Say '=================================================================' Cyan
    $c = (Read-Host 'Выберите пункт').Trim()
    Write-Host ''
    switch ($c) {
        '1'  { Show-Status; Pause-Menu }
        '2'  { Save-Version; Pause-Menu }
        '3'  { Push-Github; Pause-Menu }
        '4'  { Show-History; Pause-Menu }
        '5'  { Rollback-Code; Pause-Menu }
        '6'  { Backup-Db | Out-Null; Pause-Menu }
        '7'  { Restore-Db; Pause-Menu }
        '8'  { Start-All; Pause-Menu }
        '9'  { Stop-All; Pause-Menu }
        '10' { Rebuild; Pause-Menu }
        '11' { Show-Logs; Pause-Menu }
        '12' { Run-Tests; Pause-Menu }
        '13' { Load-Demo; Pause-Menu }
        '0'  { exit 0 }
        default { }
    }
}
