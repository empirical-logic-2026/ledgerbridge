FROM python:3.12-slim

# Keep in step with the uv version that writes uv.lock.
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /uvx /bin/

# PYTHONPATH: the project's packages (api, core, connectors, workers, ...) live in /app.
# Celery only adds the working directory to the import path while it loads the app, so
# imports made later inside tasks need /app on the path explicitly.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app"

WORKDIR /app

COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev

COPY . .

RUN useradd --system --uid 10001 app && chown -R app /app
USER app

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
