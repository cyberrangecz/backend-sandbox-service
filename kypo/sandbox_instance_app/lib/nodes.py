"""
VM Service module for VM management.
"""
from kypo.openstack_driver.ostack_general_proxy import OpenStackInstance

from kypo.sandbox_instance_app.models import Sandbox
from kypo.sandbox_common_lib import utils, exceptions


def node_action(sandbox: Sandbox, node_name: str, action: str) -> None:
    """Perform action on given node."""
    client = utils.get_ostack_client()
    action_dict = {
                  'suspend': client.suspend_node,
                  'resume': client.resume_node,
                  'reboot': client.reboot_node,
    }
    try:
        return action_dict[action](sandbox.allocation_unit.get_stack_name(), node_name)
    except KeyError:
        raise exceptions.ValidationError("Unknown action: '%s'" % action)


def get_node(sandbox: Sandbox, node_name: str) -> OpenStackInstance:
    """Retrieve Instance from OpenStack."""
    client = utils.get_ostack_client()
    return client.get_node(sandbox.allocation_unit.get_stack_name(), node_name)


def get_console_url(sandbox: Sandbox, node_name: str) -> str:
    """Get console URL for given VM."""
    client = utils.get_ostack_client()
    return client.get_spice_console(sandbox.allocation_unit.get_stack_name(), node_name)
