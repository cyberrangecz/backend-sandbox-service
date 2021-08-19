FROM python:3.8-slim

ENV DJANGO_ADMIN_USER "admin"
ENV DJANGO_ADMIN_PASSWORD "admin"
ENV DJANGO_ADMIN_EMAIL "admin@example.com"

ARG KYPO_PYPI_DOWNLOAD_URL="https://localhost.lan/repository"

RUN apt-get update && apt-get install -y python3 python3-pip python3-dev git redis libpq-dev docker nginx supervisor postgresql netcat

ENV PYTHONUNBUFFERED 1
RUN pip3 install pipenv

RUN mkdir -p /var/log/supervisor
RUN mkdir -p /run/nginx
# remove default Nginx page for fallback URI
RUN rm -rf /usr/share/nginx/html

ENV PATH="$PATH:/usr/lib/postgresql/13/bin"
ENV PGDATA "/var/lib/postgresql/data"
ENV PGUSER "postgres"
RUN mkdir -p /run/postgresql && \
    chown ${PGUSER}:${PGUSER} /run/postgresql && \
    mkdir -p ${PGDATA} && \
    chown ${PGUSER}:${PGUSER} ${PGDATA} && \
    su -c "initdb ${PGDATA}" ${PGUSER}

COPY supervisord.conf /etc/supervisord.conf
COPY etc/nginx.conf /etc/nginx/sites-available/default

COPY bin/ /app/bin/
COPY kypo/ /app/kypo/
COPY config.yml manage.py Pipfile Pipfile.lock /app/

WORKDIR /app

RUN pipenv sync && \
    pipenv run pip3 install gunicorn
# static files must be served from proxy server, expose them via volume bind
RUN pipenv run python3 manage.py collectstatic --no-input -v 2

EXPOSE 8000
ENTRYPOINT ["/app/bin/entrypoint.sh"]
