# Образ приложения Universal CRM. Сборка: docker compose build
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Зависимости отдельным слоем: при правке кода они не переустанавливаются.
# tzdata нужна для APP_TIMEZONE (в slim-образе базы часовых поясов может не быть).
COPY requirements.txt ./
RUN pip install -r requirements.txt tzdata

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY docker/entrypoint.sh /entrypoint.sh

# Не root; /data — для временных файлов импорта (том app_data).
# sed убирает переводы строк Windows, если скрипт пришёл с CRLF.
RUN sed -i 's/\r$//' /entrypoint.sh \
    && chmod +x /entrypoint.sh \
    && useradd --system --uid 10001 --home-dir /app crm \
    && mkdir -p /data/imports \
    && chown -R crm:crm /data

USER crm
ENV IMPORT_DIR=/data/imports
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

ENTRYPOINT ["/entrypoint.sh"]
