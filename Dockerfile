FROM python:3.13-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ARG MAXMIND_LICENSE_KEY=""
RUN if [ -n "$MAXMIND_LICENSE_KEY" ]; then \
      curl -fsSL "https://download.maxmind.com/app/geoip_download?edition_id=GeoLite2-City&license_key=${MAXMIND_LICENSE_KEY}&suffix=tar.gz" -o /tmp/geoip.tgz \
      && tar -xzf /tmp/geoip.tgz -C /tmp \
      && GEOFILE="$(find /tmp -name 'GeoLite2-City.mmdb' -print -quit)" \
      && if [ -n "$GEOFILE" ]; then mv "$GEOFILE" /app/GeoLite2-City.mmdb; fi \
      && rm -rf /tmp/geoip.tgz /tmp/GeoLite2-City_*; \
    fi

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV GEOIP_DB_PATH=/app/GeoLite2-City.mmdb

RUN chmod +x entrypoint.sh

EXPOSE 8000

# Shell form: expands $PORT when image CMD is used (Railway may override via railway.toml)
CMD sh -c "./entrypoint.sh"
