# ageval L1 Attempt base image — non-privileged, no Docker socket.
# Preinstalls coding-agent engines + ACP entries (Spec 19 BOM, five entries).
# Build: python -m ageval.plugins.contrib.docker.attempt.build
# Packages FROM ageval-attempt:base (or the historical l1 tag) or extend upstream.
# Python ACP SDK stays on the parent host — never installed here.

# Base CPython minor; build.py passes --build-arg to pick another 3.x.
ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim-bookworm

USER root
# Optional host build-args (empty = official Debian / PyPI). Applied before
# install-executors.sh so apt-get sees rewritten sources. Child images that
# FROM this tag inherit debian.sources + /etc/pip.conf. Do not ENV an empty
# PIP_INDEX_URL — a blank value overrides pip's default index.
ARG AGEVAL_APT_MIRROR=
ARG AGEVAL_PIP_INDEX=
RUN set -eu; \
    if [ -n "${AGEVAL_APT_MIRROR}" ]; then \
      mirror="${AGEVAL_APT_MIRROR%/}"; \
      src=/etc/apt/sources.list.d/debian.sources; \
      if [ ! -f "${src}" ]; then \
        echo "AGEVAL_APT_MIRROR set but ${src} missing" >&2; \
        exit 1; \
      fi; \
      sec="${mirror}"; \
      case "${mirror}" in \
        */debian) sec="${mirror%/debian}/debian-security" ;; \
      esac; \
      sed -i \
        -e "s|https://deb.debian.org/debian-security|${sec}|g" \
        -e "s|http://deb.debian.org/debian-security|${sec}|g" \
        -e "s|https://deb.debian.org/debian|${mirror}|g" \
        -e "s|http://deb.debian.org/debian|${mirror}|g" \
        "${src}"; \
      if [ -f /etc/apt/sources.list ]; then \
        sed -i \
          -e "s|https://deb.debian.org/debian-security|${sec}|g" \
          -e "s|http://deb.debian.org/debian-security|${sec}|g" \
          -e "s|https://deb.debian.org/debian|${mirror}|g" \
          -e "s|http://deb.debian.org/debian|${mirror}|g" \
          /etc/apt/sources.list; \
      fi; \
      printf '%s\n' \
        'Acquire::http::Proxy "false";' \
        'Acquire::https::Proxy "false";' \
        > /etc/apt/apt.conf.d/99ageval-no-proxy; \
    fi; \
    if [ -n "${AGEVAL_PIP_INDEX}" ]; then \
      index="${AGEVAL_PIP_INDEX%/}"; \
      host="${index#*://}"; \
      host="${host%%/*}"; \
      printf '%s\n' \
        '[global]' \
        "index-url = ${index}" \
        "trusted-host = ${host}" \
        > /etc/pip.conf; \
    fi

COPY sitecustomize.py /tmp/ageval-sitecustomize.py
RUN set -eu; \
    if [ -f /etc/pip.conf ]; then \
      sitepkg="$(python3 -c 'import site; print(site.getsitepackages()[0])')"; \
      cp /tmp/ageval-sitecustomize.py "${sitepkg}/sitecustomize.py"; \
    fi; \
    rm -f /tmp/ageval-sitecustomize.py

COPY install-executors.sh /tmp/install-executors.sh
COPY acp-entries.lock.json /etc/ageval/acp-entries.lock.json
RUN bash /tmp/install-executors.sh \
    && rm -f /tmp/install-executors.sh \
    && test -f /etc/ageval/acp-entries.lock.json

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin ageval \
    && mkdir -p /attempt/workspace /attempt/package /attempt/artifacts \
    && chown -R ageval:ageval /attempt

# Post-user PATH verify as actor UID 10001 (numeric non-root).
RUN set -e; \
    export PATH="/usr/local/bin:/usr/bin:/bin"; \
    su -s /bin/bash ageval -c '\
      command -v codex && command -v codex-acp && \
      command -v pi && command -v pi-acp && \
      command -v opencode && \
      (command -v claude || command -v claude-code) && command -v claude-agent-acp && \
      command -v grok \
    '

USER ageval
WORKDIR /attempt/workspace
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/usr/local/bin:/home/ageval/.local/bin:${PATH}"

CMD ["python", "-c", "print('ageval-attempt-ready')"]
