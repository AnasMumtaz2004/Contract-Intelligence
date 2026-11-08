FROM python:3.11-slim

WORKDIR /app

# CPU-only torch keeps the image much smaller than the default GPU build
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY . .
RUN pip install --no-cache-dir .

# Run migrations first, then start the API
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]