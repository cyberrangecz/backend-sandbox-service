FROM python:3.12-slim AS builder
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends gcc && \
    pip install --no-cache-dir uv && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /var/log/supervisor

RUN uv venv
COPY README.md pyproject.toml uv.lock ./
RUN uv sync

FROM python:3.12-slim AS app
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends gnupg software-properties-common curl unzip && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

## Install OpenTofu from script
RUN curl --proto '=https' --tlsv1.2 -fsSL https://get.opentofu.org/install-opentofu.sh -o install-opentofu.sh && \
chmod +x install-opentofu.sh && \
./install-opentofu.sh --install-method standalone && \
rm -rf install-opentofu.sh /tmp/*

COPY bin bin
COPY crczp crczp
COPY config.yml-template ./config.yml
COPY manage.py ./
COPY --from=builder /app/.venv ./.venv

# static files must be served from proxy server, expose them via volume bind
RUN python manage.py collectstatic --no-input -v 2

EXPOSE 8000
ENTRYPOINT ["/app/bin/run-sandbox-service.sh"]
