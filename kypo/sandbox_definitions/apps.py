from django.apps import AppConfig

from ..common import utils


class KypoSandboxDefinitionsConfig(AppConfig):
    name = __package__

    def ready(self):
        """"Perform initialization tasks (logging, registering roles to User and Group, …)."""
        utils.configure_logging()
