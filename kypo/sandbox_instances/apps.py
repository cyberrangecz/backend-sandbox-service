from django.apps import AppConfig

from ..sandbox_common import utils


class KypoSandboxInstancesConfig(AppConfig):
    name = __package__

    def ready(self):
        """"Perform initialization tasks (logging, registering roles to User and Group, …)."""
        utils.configure_logging()
