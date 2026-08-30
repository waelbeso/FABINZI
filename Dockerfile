FROM python:3.12.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt constraints-release.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt -c constraints-release.txt \
    && python -m pip check

COPY . .

# Keep the image runnable even when a hosting service does not apply the
# repository-specific command from render.yaml. Migrations are idempotent and
# collectstatic must run before Gunicorn when manifest-based WhiteNoise storage
# is enabled in production.
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py collectstatic --noinput && exec gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers ${GUNICORN_WORKERS:-3} --timeout ${GUNICORN_TIMEOUT:-120}"]
