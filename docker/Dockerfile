# ===========================================================================
#  Изолированный образ приложения. Сборка из КОРНЯ проекта:
#      docker compose -f docker/docker-compose.yml up --build
#  Обычный запуск через `python app.py` этот файл не затрагивает.
# ===========================================================================
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Зависимости отдельным слоем — быстрее пересборка.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Исходный код приложения.
COPY app.py config.py database.py models.py security.py scheduling.py utils.py \
     analytics.py assets.py ai_marketing.py integrations.py seed.py templating.py ./
COPY routers ./routers
COPY templates ./templates
COPY static ./static
COPY scripts ./scripts

# Внутри контейнера сервер слушает все интерфейсы.
ENV HOST=0.0.0.0 \
    PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)" || exit 1

CMD ["python", "app.py"]
