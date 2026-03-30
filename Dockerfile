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

RUN apt-get update && apt-get install -y --no-install-recommends gnupg curl unzip git && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

## Install OpenTofu from script
RUN curl --proto '=https' --tlsv1.2 -fsSL https://get.opentofu.org/install-opentofu.sh -o install-opentofu.sh && \
chmod +x install-opentofu.sh && \
./install-opentofu.sh --install-method standalone && \
rm -rf install-opentofu.sh /tmp/*

# Setup provider mirror
WORKDIR /opt/tofu
COPY tofu/openstack.tf .
COPY tofu/tofu.rc /opt/tofu/config/tofu.rc
RUN tofu init && tofu providers mirror /opt/tofu/provider_mirror
ENV TF_CLI_CONFIG_FILE=/opt/tofu/config/tofu.rc

WORKDIR /app

COPY bin bin
COPY ansible ansible
COPY crczp crczp
COPY config.yml-template ./config.yml
COPY manage.py ./
COPY --from=builder /app/.venv ./.venv

# Pre-install Ansible Galaxy roles (ansible-stage-one v1.5.1) into the same path the runner uses so galaxy skips already-installed roles
RUN mkdir -p /app/ansible_repo/provisioning/roles && \
    .venv/bin/ansible-galaxy install -r /app/ansible/requirements.yml -p /app/ansible_repo/provisioning/roles
ENV ANSIBLE_GALAXY_ROLES_PATH=/app/ansible_repo/provisioning/roles

# static files must be served from proxy server, expose them via volume bind
RUN python manage.py collectstatic --no-input -v 2

# Single-sandbox cleanup: runs in background when enabled. Uses default internal training URL (config or env override optional).
ENV SINGLE_SANDBOX_CLEANUP_ENABLED=true \
    SINGLE_SANDBOX_CLEANUP_AGE_HOURS=24 \
    SINGLE_SANDBOX_CLEANUP_RUN_INTERVAL_HOURS=1 \
    SINGLE_SANDBOX_CLEANUP_RETRY_FAILED=true

EXPOSE 8000
ENTRYPOINT ["/app/bin/run-sandbox-service.sh"]
