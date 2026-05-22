"""Django management command for registering roles with the User and Group service."""

from typing import Any, override

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    """Custom management command to register roles to User and Group service."""

    help = 'Register user roles to User and Group service.'
    # DB needs to be migrated, otherwise the used permissions may not exist.
    requires_migrations_checks = True

    @override
    def handle(self, *args: Any, **options: Any) -> None:
        # The authentication needs to be on, so that the auth framework has
        # all required settings. Otherwise, it dies with an ambiguous error.
        if not settings.CRCZP_SERVICE_CONFIG.authentication.authenticated_rest_api:
            raise CommandError(
                'The `authenticated_rest_api` must be turned on (set to True)'
                ' to register the roles.'
            )
        # The module can be imported only if the required settings are set. It fails otherwise.
        from crczp.sandbox_uag import auth  # pylint: disable=import-outside-toplevel

        auth.post_user_roles()
