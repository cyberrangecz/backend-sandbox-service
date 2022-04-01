FROM python:3.8-slim as builder
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIPENV_VENV_IN_PROJECT="enabled"

ARG KYPO_PYPI_DOWNLOAD_URL="https://localhost.lan/repository"

RUN pip3 install pipenv

RUN mkdir -p /var/log/supervisor

COPY manage.py Pipfile Pipfile.lock ./
RUN pipenv sync
RUN pipenv run pip3 install gunicorn

FROM python:3.8-slim as app
WORKDIR /app

ENV DJANGO_ADMIN_USER "admin"
ENV DJANGO_ADMIN_PASSWORD "admin"
ENV DJANGO_ADMIN_EMAIL "admin@example.com"

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:$PATH"

RUN apt-get update && apt-get install -y git redis supervisor netcat gnupg software-properties-common curl

## Install Terraform
RUN curl -fsSL https://apt.releases.hashicorp.com/gpg | apt-key add -
RUN apt-add-repository "deb [arch=amd64] https://apt.releases.hashicorp.com $(lsb_release -cs) main"
RUN apt-get update && apt-get install -y terraform

COPY bin bin
COPY kypo kypo
COPY config.yml manage.py ./
COPY --from=builder /app/.venv ./.venv

COPY supervisord.conf /etc/supervisord.conf
RUN mkdir -p /var/log/supervisor

# static files must be served from proxy server, expose them via volume bind
RUN python3 manage.py collectstatic --no-input -v 2

EXPOSE 8000
ENTRYPOINT ["/app/bin/entrypoint.sh"]
