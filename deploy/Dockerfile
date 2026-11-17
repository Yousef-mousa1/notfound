FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HARMONIZER_CONFIG=/app/backend/config/cloudrun.yaml

RUN apt-get update \
 && apt-get install -y --no-install-recommends nginx apache2-utils \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend /app/backend
COPY modeling/outputs /app/modeling/outputs

RUN python -m pip install --no-cache-dir -e /app/backend gunicorn \
 && mkdir -p /app/backend/data/processed/exports \
             /app/backend/data/interim/uploads \
             /var/log/nginx /run

COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY deploy/start.sh /usr/local/bin/start.sh
RUN rm -f /etc/nginx/sites-enabled/default \
 && chmod +x /usr/local/bin/start.sh

EXPOSE 8080
CMD ["/usr/local/bin/start.sh"]
