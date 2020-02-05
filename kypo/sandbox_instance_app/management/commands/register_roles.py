from django.core.management.base import BaseCommand
from csirtmu.uag_auth import auth


class Command(BaseCommand):
    """Custom management command to register roles to User and Group service."""

    help = 'Register user roles to User and Group service.'

    def handle(self, **options):
        import os
        print(os. getcwd())
        auth.post_user_roles()
