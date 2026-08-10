ARG BUILD_FROM=ghcr.io/hassio-addons/debian-base:9.1.0
# hadolint ignore=DL3006
FROM ${BUILD_FROM}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# ---------------------------------------------------------------------------
# Layer A (rarely changes): system packages + Python deps from pyproject.
# Keep ABOVE COPY of app code / rootfs so script-only edits reuse the cache.
# ---------------------------------------------------------------------------
ARG BUILD_ARCH=amd64
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    XIAOMUSIC_APP_ROOT=/app \
    PATH=/app/.venv/bin:/usr/local/bin:$PATH \
    TZ=Asia/Shanghai

WORKDIR /app

COPY pyproject.toml README.md ./

RUN \
    apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        python3-venv \
        python3-dev \
        build-essential \
        ffmpeg \
        nodejs \
        npm \
        ca-certificates \
        curl \
        zlib1g-dev \
        libjpeg-dev \
        libfreetype6-dev \
        liblcms2-dev \
        libopenjp2-7-dev \
        libtiff5-dev \
        libwebp-dev \
    \
    && python3 -m venv /app/.venv \
    && /app/.venv/bin/pip install -U pip setuptools wheel \
    && /app/.venv/bin/pip install \
        "aiohttp>=3.8.6" \
        "watchdog>=6.0.0" \
        "mutagen>=1.47.0" \
        "yt-dlp[default]>=2024.12.1" \
        "uvicorn>=0.30.1" \
        "fastapi>=0.115.4" \
        "starlette>=0.37.2" \
        "aiofiles>=24.1.0" \
        "ga4mp>=2.0.4" \
        "apscheduler>=3.10.4" \
        "opencc-python-reimplemented==0.1.7" \
        "pillow>=10.4.0" \
        "python-multipart>=0.0.12" \
        "requests>=2.32.3" \
        "sentry-sdk[fastapi]==1.45.1" \
        "pyjwt>=2.10.1" \
        "fake-useragent>=2.2.0" \
        "miservice-fork" \
        "edge-tts>=7.2.3" \
        "psutil>=5.9.0" \
        "pycryptodome>=3.23.0" \
        "qrcode>=8.2" \
    \
    && apt-get purge -y --auto-remove \
        build-essential \
        python3-dev \
        zlib1g-dev \
        libjpeg-dev \
        libfreetype6-dev \
        liblcms2-dev \
        libopenjp2-7-dev \
        libtiff5-dev \
        libwebp-dev \
    && apt-mark manual \
        python3 \
        python3-venv \
        ffmpeg \
        nodejs \
        npm \
        ca-certificates \
        curl \
    && rm -fr \
        /tmp/* \
        /var/{cache,log}/* \
        /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Layer B: application code (changes more often than deps).
# ---------------------------------------------------------------------------
COPY xiaomusic/ ./xiaomusic/
COPY plugins/ ./plugins/
COPY holiday/ ./holiday/
COPY xiaomusic.py ./

RUN \
    mkdir -p /app/ffmpeg/bin /app/conf /app/music \
    && ln -sf "$(command -v ffmpeg)" /app/ffmpeg/bin/ffmpeg \
    && ln -sf "$(command -v ffprobe)" /app/ffmpeg/bin/ffprobe \
    && touch /app/.dockerenv

# ---------------------------------------------------------------------------
# Layer C: s6 / entrypoint (changes most often).
# ---------------------------------------------------------------------------
COPY ha_xiaomusic/rootfs /

RUN \
    chmod a+x /usr/bin/xiaomusic-ha.py \
    && chmod a+x /usr/bin/xiaomusic-ui.py \
    && chmod a+x /etc/s6-overlay/s6-rc.d/xiaomusic/run \
    && chmod a+x /etc/s6-overlay/s6-rc.d/xiaomusic/finish \
    && chmod a+x /etc/s6-overlay/s6-rc.d/xiaomusic-ui/run \
    && chmod a+x /etc/s6-overlay/s6-rc.d/xiaomusic-ui/finish

WORKDIR /app

ARG BUILD_ARCH
ARG BUILD_DATE
ARG BUILD_DESCRIPTION
ARG BUILD_NAME
ARG BUILD_REF
ARG BUILD_REPOSITORY
ARG BUILD_VERSION

LABEL \
    io.hass.name="${BUILD_NAME}" \
    io.hass.description="${BUILD_DESCRIPTION}" \
    io.hass.arch="${BUILD_ARCH}" \
    io.hass.type="addon" \
    io.hass.version=${BUILD_VERSION} \
    maintainer="yakamoz423" \
    org.opencontainers.image.title="${BUILD_NAME}" \
    org.opencontainers.image.description="${BUILD_DESCRIPTION}" \
    org.opencontainers.image.vendor="XiaoMusic" \
    org.opencontainers.image.authors="yakamoz423" \
    org.opencontainers.image.licenses="MIT" \
    org.opencontainers.image.url="https://github.com/yakamoz423/xiaomusic" \
    org.opencontainers.image.source="https://github.com/${BUILD_REPOSITORY}" \
    org.opencontainers.image.documentation="https://github.com/${BUILD_REPOSITORY}/blob/main/ha_xiaomusic/DOCS.md" \
    org.opencontainers.image.created=${BUILD_DATE} \
    org.opencontainers.image.revision=${BUILD_REF} \
    org.opencontainers.image.version=${BUILD_VERSION}
