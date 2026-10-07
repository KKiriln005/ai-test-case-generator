# syntax=docker/dockerfile:1

# ---- Stage 1: збирання віртуального оточення ----
FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
# Спершу лише requirements: шар із залежностями кешується, поки файл не змінювався.
COPY requirements.txt .
RUN pip install -r requirements.txt

# ---- Stage 2: мінімальний рантайм ----
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# Запуск не від root. Ім'я `appuser` (UID/GID 10001) - єдине для Dockerfile і документації;
# воно не збігається з каталогом /app і пакетом `app`, тому не плутається з ними.
RUN groupadd --system --gid 10001 appuser \
 && useradd --system --uid 10001 --gid appuser --no-create-home --home-dir /nonexistent appuser
WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY app ./app

USER appuser
EXPOSE 8000

# У slim-образі немає curl, тому healthcheck на стандартній бібліотеці Python.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/health', timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
