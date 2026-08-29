#!/bin/sh
set -eu

python manage.py reconcile_migration_state
python manage.py migrate --noinput
python manage.py collectstatic --noinput
exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-10000}" \
  --workers "${GUNICORN_WORKERS:-2}" \
  --timeout "${GUNICORN_TIMEOUT:-120}"
