#!/usr/bin/env sh

LISTEN_IP=0.0.0.0
LISTEN_PORT=80

CREATE_SUPERUSER="
from django.contrib.auth.models import User
from django.db.utils import IntegrityError
try:
    User.objects.create_superuser('${DJANGO_ADMIN_USER}', '${DJANGO_ADMIN_EMAIL}', '${DJANGO_ADMIN_PASSWORD}')
except IntegrityError:
    print('superuser \'${DJANGO_ADMIN_USER}\' already exists')
"

set -e

pipenv run python manage.py migrate
pipenv run python manage.py createcachetable
pipenv run python manage.py shell << EOF
${CREATE_SUPERUSER}
EOF
pipenv run python manage.py register_roles
pipenv run gunicorn --bind ${LISTEN_IP}:${LISTEN_PORT} kypo.sandbox_service_project.wsgi:application
