#!/usr/bin/env sh

LISTEN_IP=0.0.0.0
LISTEN_PORT=8000

CREATE_SUPERUSER="
from django.contrib.auth.models import User
from django.db.utils import IntegrityError
try:
    User.objects.create_superuser('${DJANGO_ADMIN_USER}', '${DJANGO_ADMIN_EMAIL}', '${DJANGO_ADMIN_PASSWORD}')
except IntegrityError:
    print('superuser \'${DJANGO_ADMIN_USER}\' already exists')
"

set -e

python manage.py migrate
python manage.py createcachetable
python manage.py shell << EOF
${CREATE_SUPERUSER}
EOF
python manage.py register_roles
gunicorn --bind ${LISTEN_IP}:${LISTEN_PORT} --timeout 600 --workers 5 crczp.sandbox_service_project.wsgi:application
