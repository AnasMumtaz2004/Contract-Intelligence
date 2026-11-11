# The Python version must match requires-python in pyproject.toml
ARG PYTHON_VERSION=3.14
FROM python:${PYTHON_VERSION}-slim

# uv installs the exact versions from uv.lock
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Tesseract reads scanned pages. libgomp1 is needed by the machine learning libraries.

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        libgomp1 \
        build-essential \
    && rm -rf /var/lib/apt/lists/*


WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# The dependencies are installed first, so Docker reuses this step when only the code changes
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .

EXPOSE 8000
# The database is migrated on every start, then the API runs
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]