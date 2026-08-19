FROM python:3.12.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:$PATH \
    PORT=8000 \
    SIDESTAGE_DATABASE_PATH=/var/data/sidestage.sqlite3

WORKDIR /app

RUN pip install --no-cache-dir uv==0.10.11

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY fixtures ./fixtures

RUN uv sync --frozen --no-dev
RUN mkdir -p /var/data

EXPOSE 8000

CMD ["/bin/sh", "-c", "exec uvicorn sidestage.app:create_challenge_app --factory --host 0.0.0.0 --port ${PORT}"]
