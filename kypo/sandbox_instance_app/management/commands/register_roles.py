from django.core.management.base import BaseCommand, CommandError
from django.conf import settings


class Command(BaseCommand):
    """Custom management command to register roles to User and Group service."""

    help = 'Register user roles to User and Group service.'
    # DB needs to be migrated, otherwise the used permissions may not exist.
    requires_migrations_checks = True

    def handle(self, **options):
        # The authentication needs to be on, so that the auth framework has
        # all required settings. Otherwise, it dies with an ambiguous error.
        if not settings.KYPO_SERVICE_CONFIG.authentication.authenticated_rest_api:
            raise CommandError(
                'The `authenticated_rest_api` must be turned on (set to True) to register the roles.'
            )
        # The module can be imported only if the required settings are set. It fails otherwise.
        from kypo.sandbox_uag.uag_auth import auth
        auth.post_user_roles()
