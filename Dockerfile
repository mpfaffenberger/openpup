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

RUN pip install ".[all]"

# OpenPup state (kennel, routines, counters) lives here; mount a volume.
ENV PUPPY_KENNEL_ROOT=/data/kennel
VOLUME ["/data"]

# Webhook server port (WhatsApp/SMS inbound)
EXPOSE 8080

ENTRYPOINT ["openpup"]
CMD ["run"]
