"""Django app configuration for the sandbox instance app."""

from typing import override

from django.apps import AppConfig

from crczp.sandbox_common_lib import utils


class CrczpSandboxInstanceAppConfig(AppConfig):
    """App configuration for CRCZP sandbox instance application."""

    name = __package__

    @override
    def ready(self) -> None:
        """ "Perform initialization tasks (logging, registering roles to User and Group, …)."""
        utils.configure_logging()
