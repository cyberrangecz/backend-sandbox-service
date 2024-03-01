FROM python:3.12-slim as builder
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIPENV_VENV_IN_PROJECT="true"

RUN pip3 install pipenv
RUN apt-get update && apt-get install -y gcc

RUN mkdir -p /var/log/supervisor

COPY manage.py Pipfile Pipfile.lock ./
RUN pipenv sync
RUN pipenv run pip3 install gunicorn setuptools

FROM python:3.12-slim as app
WORKDIR /app

ARG DJNG_ADMIN_USER="admin"
ARG DJNG_ADMIN_PASSWORD="PmOn78IbUv12"
ENV DJANGO_ADMIN_USER=$DJNG_ADMIN_USER
ENV DJANGO_ADMIN_PASSWORD=$DJNG_ADMIN_PASSWORD
ENV DJANGO_ADMIN_EMAIL "admin@example.com"

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:$PATH"

RUN apt-get update && apt-get install -y git gnupg software-properties-common curl

## Install OpenTofu from script
RUN apt-get install unzip

RUN curl --proto '=https' --tlsv1.2 -fsSL https://get.opentofu.org/install-opentofu.sh -o install-opentofu.sh
RUN chmod +x install-opentofu.sh
RUN ./install-opentofu.sh --install-method standalone
RUN rm install-opentofu.sh

COPY bin bin
COPY crczp crczp
COPY config.yml-template ./config.yml
COPY manage.py ./
COPY --from=builder /app/.venv ./.venv

# static files must be served from proxy server, expose them via volume bind
RUN python3 manage.py collectstatic --no-input -v 2

EXPOSE 8000
ENTRYPOINT ["/app/bin/run-sandbox-service.sh"]
