# Specta — one image: FastAPI backend + static frontend
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY static ./static
COPY config ./config
COPY kb ./kb
COPY samples ./samples
COPY scripts ./scripts
COPY supabase ./supabase

# persistent cache of agent answers + team experience
RUN useradd --create-home specta && mkdir -p /app/data && chown -R specta /app/data
USER specta
VOLUME ["/app/data"]

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/config', timeout=4)" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
