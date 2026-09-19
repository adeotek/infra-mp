# InfraMP — single-container deployment
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    INFRAMP_DATA_DIR=/data \
    UV_LINK_MODE=copy

WORKDIR /app

# Install uv (the project's locked package manager) from its published image.
COPY --from=ghcr.io/astral-sh/uv:0.7.1 /uv /uvx /bin/

# Install the application and its dependencies from uv.lock (frozen: the
# exact locked versions tested by CI, regardless of newer releases) — the
# pyproject ranges alone would float to the newest versions on every rebuild.
COPY pyproject.toml uv.lock README.md ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
RUN uv sync --frozen --no-dev --no-editable

# The SQLite database lives on a persistent volume.
VOLUME /data
EXPOSE 8000

# Run as a non-root user. /data is owned by this uid; on first use Docker
# copies the image's /data ownership into the named volume. When upgrading an
# EXISTING volume created by a pre-0.7.0 (root-running) image, chown it once:
#   docker run --rm -v infra-mp-data:/data alpine chown -R 10001:10001 /data
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin inframp \
    && mkdir -p /data \
    && chown inframp:inframp /data
USER inframp

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
  CMD /app/.venv/bin/python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" || exit 1

# Run migrations, then serve. Use exec so uvicorn receives signals directly.
# uv sync puts the environment in /app/.venv.
CMD ["sh", "-c", ".venv/bin/alembic upgrade head && exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000"]