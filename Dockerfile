# InfraMP — single-container deployment
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    INFRAMP_DATA_DIR=/data

WORKDIR /app

# Install the application and its dependencies (templates + static are bundled
# in the wheel, verified at build time).
COPY pyproject.toml README.md ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
RUN pip install --no-cache-dir .

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
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" || exit 1

# Run migrations, then serve. Use exec so uvicorn receives signals directly.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
