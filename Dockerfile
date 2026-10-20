# One image: the built frontend, served by the FastAPI backend on one origin.
# Versions are pinned to what CI and development use.

# --- Frontend ---------------------------------------------------------------
FROM node:20.20.2-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# --- Backend ----------------------------------------------------------------
FROM python:3.12.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.22 /uv /usr/local/bin/uv
ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/srv/.venv/bin:$PATH"
WORKDIR /srv

# Dependencies first, so they are cached while the code changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY migrations ./migrations
COPY prompts ./prompts
COPY app ./app
COPY deploy/start.sh ./deploy/start.sh
RUN uv sync --frozen --no-dev
COPY --from=web /web/dist ./web/dist

# Not root.
RUN useradd --uid 10001 --no-create-home recruitdesk
USER recruitdesk

EXPOSE 8000
CMD ["sh", "deploy/start.sh"]
