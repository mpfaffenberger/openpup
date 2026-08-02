FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps (some platform libs build wheels; keep it lean)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src

# Keep the published image feature-complete by default. Narrow deployments can
# override this (for example: --build-arg OPENPUP_INSTALL_SPEC=.) instead of
# downloading browser, voice, and every chat platform dependency.
ARG OPENPUP_INSTALL_SPEC=".[all]"
RUN pip install "$OPENPUP_INSTALL_SPEC"

# OpenPup state (kennel, routines, counters) lives here; mount a volume.
ENV PUPPY_KENNEL_ROOT=/data/kennel
VOLUME ["/data"]

# Webhook server port (WhatsApp/SMS inbound)
EXPOSE 8080

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["openpup", "run"]
