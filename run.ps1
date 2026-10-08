<#
  Universal CRM: запуск проекта в Docker и публичного туннеля Cloudflare одной командой.
  Запуск: двойной клик по run.bat (или  powershell -ExecutionPolicy Bypass -File .\run.ps1).
  Остановка: Ctrl+C в этом окне (туннель закрывается, контейнеры останавливаются, данные сохраняются).
#>
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
Set-Location -LiteralPath $PSScriptRoot

$EnvFile      = '.env.docker'
$AppUrl       = 'http://localhost:8000'
$ReadyTimeout = 120   # сек: ждать готовности веб-сервиса
$UrlTimeout   = 20    # сек: искать ссылку туннеля в выводе cloudflared

function Stop-WithMessage([string]$Message, [string]$Color = 'Yellow') {
    Write-Host ''
    Write-Host $Message -ForegroundColor $Color
    Write-Host ''
    exit 1
}

# Читает файл, даже если в него в этот момент пишет другой процесс.
function Read-SharedText([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return '' }
    try {
        $fs = [IO.File]::Open($Path, 'Open', 'Read', 'ReadWrite')
        try { return (New-Object IO.StreamReader($fs)).ReadToEnd() } finally { $fs.Dispose() }
    } catch { return '' }
}

# ---------------------------------------------------------------- 0. предварительные проверки
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Stop-WithMessage 'Docker не найден. Установите Docker Desktop: https://www.docker.com/products/docker-desktop/'
}
if (-not (Test-Path -LiteralPath $EnvFile)) {
    Stop-WithMessage "Не найден файл $EnvFile в папке проекта. Создайте его по инструкции в README (раздел «Docker»)."
}
$cloudflared = Get-Command cloudflared -ErrorAction SilentlyContinue
if (-not $cloudflared) {
    Stop-WithMessage ("Не найден cloudflared. Установите его командой:`n  winget install --id Cloudflare.cloudflared`n" +
                      "затем закройте это окно и запустите run.bat снова.")
}

# ---------------------------------------------------------------- 1. Docker Desktop запущен? Если нет — запускаем сами
$DockerStartTimeout = 240   # сек: Docker Desktop стартует долго, особенно после включения компьютера

function Test-DockerEngine {
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'   # у docker stderr при перенаправлении в PowerShell 5.1 не должен становиться ошибкой
    try { & docker info 2>&1 | Out-Null; return ($LASTEXITCODE -eq 0) } finally { $ErrorActionPreference = $old }
}

if (-not (Test-DockerEngine)) {
    $candidates = @(
        (Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Docker\Docker\Docker Desktop.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Docker\Docker\Docker Desktop.exe')
    )
    $dockerExe = $candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
    if (-not $dockerExe) {
        Stop-WithMessage ("Docker Desktop не запущен, и я не нашёл его для автозапуска.`n" +
                          "Запустите Docker Desktop вручную и повторите запуск.")
    }
    if (-not (Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue)) {
        Write-Host 'Docker Desktop не запущен — запускаю...' -ForegroundColor Cyan
        Start-Process -FilePath $dockerExe
    } else {
        Write-Host 'Docker Desktop запускается, жду готовности движка...' -ForegroundColor Cyan
    }
    $deadline = (Get-Date).AddSeconds($DockerStartTimeout)
    $up = $false
    while ((Get-Date) -lt $deadline) {
        if (Test-DockerEngine) { $up = $true; break }
        Write-Host '.' -NoNewline -ForegroundColor DarkGray
        Start-Sleep -Seconds 3
    }
    Write-Host ''
    if (-not $up) {
        Stop-WithMessage ("Docker не стал готов за $DockerStartTimeout с.`n" +
                          "Откройте Docker Desktop, дождитесь «Engine running» (при первом запуске может потребоваться принять условия) и повторите.")
    }
}
Write-Host 'Docker работает.' -ForegroundColor Green

$tunnel = $null
$outLog = Join-Path $env:TEMP 'crm-cloudflared.out.log'
$errLog = Join-Path $env:TEMP 'crm-cloudflared.err.log'

try {
    # ------------------------------------------------------------ 2. контейнеры
    Write-Host 'Запускаю контейнеры CRM...' -ForegroundColor Cyan
    & docker compose --env-file $EnvFile up -d
    if ($LASTEXITCODE -ne 0) {
        Stop-WithMessage 'Не удалось запустить контейнеры (см. сообщение выше).' 'Red'
    }

    # ------------------------------------------------------------ 3. ждём готовности веб-сервиса
    Write-Host "Жду готовности $AppUrl (до $ReadyTimeout с)..." -ForegroundColor Cyan
    $deadline = (Get-Date).AddSeconds($ReadyTimeout)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri "$AppUrl/health" -UseBasicParsing -TimeoutSec 3
            if ($r.StatusCode -eq 200) { $ready = $true; break }
        } catch { }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) {
        Stop-WithMessage ("Сервис не ответил за $ReadyTimeout с. Посмотрите журнал:`n" +
                          "  docker compose --env-file $EnvFile logs app") 'Red'
    }
    Write-Host 'CRM готова.' -ForegroundColor Green

    # ------------------------------------------------------------ 4. туннель Cloudflare (в фоне)
    Remove-Item -LiteralPath $outLog, $errLog -ErrorAction SilentlyContinue
    Write-Host 'Запускаю туннель Cloudflare (HTTP/2)...' -ForegroundColor Cyan
    $tunnel = Start-Process -FilePath $cloudflared.Source `
        -ArgumentList @('tunnel', '--protocol', 'http2', '--url', $AppUrl) `
        -RedirectStandardOutput $outLog -RedirectStandardError $errLog `
        -WindowStyle Hidden -PassThru

    # ------------------------------------------------------------ 5. ищем ссылку в выводе
    $publicUrl = $null
    $deadline = (Get-Date).AddSeconds($UrlTimeout)
    $pattern  = 'https://(?!api\.)[a-z0-9][a-z0-9-]*\.trycloudflare\.com'
    while ((Get-Date) -lt $deadline) {
        $text = (Read-SharedText $outLog) + "`n" + (Read-SharedText $errLog)
        $m = [regex]::Match($text, $pattern)
        if ($m.Success) { $publicUrl = $m.Value; break }
        if ($tunnel.HasExited) { break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $publicUrl) {
        $tail = ((Read-SharedText $errLog) + (Read-SharedText $outLog)).Trim()
        if ($tail.Length -gt 1500) { $tail = $tail.Substring($tail.Length - 1500) }
        Write-Host ''
        Write-Host "Ссылка туннеля не появилась за $UrlTimeout с. Последний вывод cloudflared:" -ForegroundColor Red
        Write-Host $tail -ForegroundColor DarkGray
        Stop-WithMessage 'Проверьте интернет-соединение и повторите запуск.' 'Red'
    }

    # ------------------------------------------------------------ 6-7. показываем и открываем
    Write-Host ''
    Write-Host '=====================================================' -ForegroundColor Green
    Write-Host '  Публичная ссылка на CRM:' -ForegroundColor Green
    Write-Host "  $publicUrl" -ForegroundColor Black -BackgroundColor Green
    Write-Host '  Локально: http://localhost:8000' -ForegroundColor Green
    Write-Host '=====================================================' -ForegroundColor Green
    Write-Host 'Ссылка доступна всем, у кого она есть, пока работает это окно. Используйте надёжные пароли.' -ForegroundColor Yellow
    Start-Process $publicUrl

    # ------------------------------------------------------------ 8. держим туннель открытым
    Write-Host ''
    Write-Host 'Нажмите Ctrl+C для остановки туннеля и сервера' -ForegroundColor Cyan
    while ($true) {
        Start-Sleep -Seconds 1
        if ($tunnel.HasExited) {
            Write-Host 'Туннель неожиданно остановился. Журнал: ' $errLog -ForegroundColor Red
            break
        }
    }
}
finally {
    Write-Host ''
    Write-Host 'Останавливаю туннель и сервер...' -ForegroundColor Cyan
    if ($tunnel -and -not $tunnel.HasExited) { Stop-Process -Id $tunnel.Id -Force -ErrorAction SilentlyContinue }
    $ErrorActionPreference = 'Continue'
    & docker compose --env-file $EnvFile stop 2>&1 | Out-Null   # stop, а не down: данные и тома остаются
    Write-Host 'Остановлено. Данные сохранены.' -ForegroundColor Green
}
