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

# Optional: background loop for single-sandbox cleanup. Run once immediately, then wait RUN_SECS between runs
# (easier to troubleshoot: no wait before first run; logs show cleanup right after startup).
if [ "${SINGLE_SANDBOX_CLEANUP_ENABLED}" = "true" ]; then
  RUN_HOURS="${SINGLE_SANDBOX_CLEANUP_RUN_INTERVAL_HOURS:-1}"
  RUN_SECS=$((RUN_HOURS * 3600))
  ( while true; do python manage.py cleanup_single_sandbox_allocations; sleep "$RUN_SECS"; done ) &
fi

gunicorn --bind ${LISTEN_IP}:${LISTEN_PORT} --timeout 600 --workers 5 crczp.sandbox_service_project.wsgi:application
