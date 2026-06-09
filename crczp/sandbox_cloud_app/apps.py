"""Django app configuration for the sandbox cloud application."""

from typing import override

from django.apps import AppConfig

from crczp.sandbox_common_lib import utils


class ProjectQuotasConfig(AppConfig):
    """App config for the sandbox cloud application."""

    name = __package__

    @override
    def ready(self) -> None:
        """Perform initialization tasks (logging, registering roles to User and Group, …)."""
        utils.configure_logging()
