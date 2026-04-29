from django.apps import AppConfig

from crczp.sandbox_common_lib import utils


class CrczpSandboxAnsibleAppConfig(AppConfig):
    name = __package__

    def ready(self):
        """ "Perform initialization tasks (logging, registering roles to User and Group, …)."""
        utils.configure_logging()
