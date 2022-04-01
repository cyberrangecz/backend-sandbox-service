"""
VM Service module for VM management.
"""
from django.conf import settings

from kypo.terraform_driver import TerraformInstance

from kypo.sandbox_instance_app.models import Sandbox
from kypo.sandbox_common_lib import utils, exceptions


def node_action(sandbox: Sandbox, node_name: str, action: str) -> None:
    """Perform action on given node."""
    client = utils.get_terraform_client()
    action_dict = {
        'resume': client.resume_node,
        'reboot': client.reboot_node,
    }
    try:
        return action_dict[action](sandbox.allocation_unit.get_stack_name(), node_name)
    except KeyError:
        raise exceptions.ValidationError("Unknown action: '%s'" % action)


def get_node(sandbox: Sandbox, node_name: str) -> TerraformInstance:
    """Retrieve Instance from OpenStack."""
    client = utils.get_terraform_client()
    return client.get_node(sandbox.allocation_unit.get_stack_name(), node_name)


def get_console_url(sandbox: Sandbox, node_name: str) -> str:
    """Get console URL for given VM."""
    client = utils.get_terraform_client()
    return client.get_console_url(sandbox.allocation_unit.get_stack_name(), node_name,
                                  settings.KYPO_CONFIG.os_console_type.value)
