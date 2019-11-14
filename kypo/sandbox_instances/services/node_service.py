"""
VM Service module for VM management.
"""
from ...common import utils, exceptions
from ..models import Sandbox
from kypo2_openstack_lib.instance import Instance


def node_action(sandbox: Sandbox, node_name: str, action: str) -> None:
    """Perform action on given node."""
    client = utils.get_ostack_client()
    action_dict = {
                  'suspend': client.suspend_node,
                  'resume': client.resume_node,
                  'reboot': client.reboot_node,
    }
    try:
        return action_dict[action](sandbox.get_stack_name(), node_name)
    except KeyError:
        raise exceptions.ValidationError("Unknown action: '%s'" % action)


def get_node(sandbox: Sandbox, node_name: str) -> Instance:
    """Retrieve Instance from OpenStack."""
    client = utils.get_ostack_client()
    return client.get_node(sandbox.get_stack_name(), node_name)


def get_console_url(sandbox: Sandbox, node_name: str) -> str:
    """Get console URL for given VM."""
    client = utils.get_ostack_client()
    return client.get_spice_console(sandbox.get_stack_name(), node_name)
