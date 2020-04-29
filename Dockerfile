FROM python:3.6.8-alpine3.10

ENV DJANGO_ADMIN_USER "admin"
ENV DJANGO_ADMIN_PASSWORD "admin"
ENV DJANGO_ADMIN_EMAIL "admin@example.com"

ARG KYPO_NEXUS_URL="https://localhost.lan/repository"

RUN apk update && apk add make gcc git python3 python3-dev musl-dev libffi-dev redis postgresql postgresql-dev openssh-client docker lighttpd

ENV PYTHONUNBUFFERED 1
RUN pip install pip --upgrade && pip install pipenv supervisor

RUN mkdir -p /var/log/supervisor

ENV PGDATA "/var/lib/postgresql/data"
ENV PGUSER "postgres"
RUN mkdir -p /run/postgresql && \
    chown ${PGUSER}:${PGUSER} /run/postgresql && \
    mkdir -p ${PGDATA} && \
    chown ${PGUSER}:${PGUSER} ${PGDATA} && \
    su -c "initdb ${PGDATA}" ${PGUSER}

COPY . /app
WORKDIR /app

RUN pipenv sync && \
    pipenv run pip install gunicorn
# static files must be served from proxy server, expose them via volume bind
RUN pipenv run python manage.py collectstatic --no-input -v 2

EXPOSE 8000
CMD supervisord -c supervisord.conf
