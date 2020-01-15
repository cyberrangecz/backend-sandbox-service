FROM python:3.6.8-alpine3.10

ENV DJANGO_ADMIN_USER "admin"
ENV DJANGO_ADMIN_PASSWORD "admin"
ENV DJANGO_ADMIN_EMAIL "admin@example.com"

RUN apk update && apk add make gcc git python3 python3-dev musl-dev libffi-dev postgresql-dev

ENV PYTHONUNBUFFERED 1
RUN pip install pipenv

RUN mkdir -p /opt/kypo-django-openstack
COPY . /opt/kypo-django-openstack

WORKDIR /opt/kypo-django-openstack

RUN pipenv sync
RUN pipenv run pip install gunicorn

# these files must be served from proxy server later, expose them via volume bind
RUN pipenv run python manage.py collectstatic --no-input -v 2

EXPOSE 8000

CMD bin/gunicorn_prod.sh

# BUILD
# docker build . -t kypo/django-sandbox

# PROD
# docker run -it -p 8000:8000 kypo/django-sandbox

# DEVEL
# docker run -it -p 8000:8000 kypo/django-sandbox bin/runserver_dev.sh
