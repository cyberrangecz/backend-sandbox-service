from django.apps import AppConfig

from ..sandbox_common_lib import utils


class KypoSandboxAnsibleRunsConfig(AppConfig):
    name = __package__

    def ready(self):
        """"Perform initialization tasks (logging, registering roles to User and Group, …)."""
        utils.configure_logging()
