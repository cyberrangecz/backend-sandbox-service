"""Django app configuration for the sandbox cloud application."""

from django.apps import AppConfig

from crczp.sandbox_common_lib import utils


class ProjectQuotasConfig(AppConfig):
    """App config for the sandbox cloud application."""

    name = __package__

    def ready(self):
        """Perform initialization tasks (logging, registering roles to User and Group, …)."""
        utils.configure_logging()
