# ---- build: install the app and its pinned deps into a venv ----
FROM python:3.12.8-slim-bookworm AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /src
RUN python -m venv /opt/venv
COPY pyproject.toml ./
COPY app ./app
RUN /opt/venv/bin/pip install .

# ---- runtime: slim image, no build tools, non-root ----
FROM python:3.12.8-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    INVENTORY_PATH=/app/data/inventory.json \
    DATABASE_URL=sqlite:////app/var/mini_gauntlet.db \
    SCAN_WORKERS=4

RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home app \
 && mkdir -p /app/var /app/data \
 && chown app:app /app/var

COPY --from=build /opt/venv /opt/venv
WORKDIR /app
USER app

EXPOSE 8000
VOLUME ["/app/var"]

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2).status == 200 else 1)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
