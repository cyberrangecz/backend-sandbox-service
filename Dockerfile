FROM python:3.8-slim as builder
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIPENV_VENV_IN_PROJECT="true"

ARG KYPO_PYPI_DOWNLOAD_URL="https://localhost.lan/repository"

RUN pip3 install pipenv==2022.4.21

RUN mkdir -p /var/log/supervisor

COPY manage.py Pipfile Pipfile.lock ./
RUN pipenv sync
RUN pipenv run pip3 install gunicorn

FROM python:3.8-slim as app
WORKDIR /app

ARG DJNG_ADMIN_USER="admin"
ARG DJNG_ADMIN_PASSWORD="PmOn78IbUv12"
ENV DJANGO_ADMIN_USER=$DJNG_ADMIN_USER
ENV DJANGO_ADMIN_PASSWORD=$DJNG_ADMIN_PASSWORD
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
