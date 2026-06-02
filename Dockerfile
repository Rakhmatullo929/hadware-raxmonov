FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# DejaVu fonts (PDF Cyrillic), gettext (compilemessages), curl (supercronic)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fonts-dejavu-core gettext curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# supercronic — container-friendly cron; jobs inherit the container environment.
ARG SUPERCRONIC_VERSION=v0.2.46
ARG SUPERCRONIC_SHA1=5bcefed628e32adc08e32634db2d10e9230dbca0
RUN curl -fsSL --retry 3 -o /usr/local/bin/supercronic \
      "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-amd64" \
    && echo "${SUPERCRONIC_SHA1}  /usr/local/bin/supercronic" | sha1sum -c - \
    && chmod +x /usr/local/bin/supercronic

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

# Compile ru/uz translations to .mo files
RUN python manage.py compilemessages

RUN chmod +x deploy/entrypoint.sh deploy/deploy.sh

EXPOSE 8000
ENTRYPOINT ["deploy/entrypoint.sh"]
CMD ["gunicorn", "rental_track.wsgi:application", \
     "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60", \
     "--access-logfile", "-", "--error-logfile", "-"]
