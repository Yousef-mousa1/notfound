#!/bin/sh
set -eu

: "${PYROSCOPE_BASIC_USER:?PYROSCOPE_BASIC_USER is required}"
: "${PYROSCOPE_BASIC_PASSWORD:?PYROSCOPE_BASIC_PASSWORD is required}"

htpasswd -b -c /etc/nginx/.htpasswd \
  "$PYROSCOPE_BASIC_USER" "$PYROSCOPE_BASIC_PASSWORD"

cd /app/backend
gunicorn --bind 127.0.0.1:8000 \
         --workers 1 --threads 2 \
         --timeout 300 \
         wsgi:application &

exec nginx -g 'daemon off;'
