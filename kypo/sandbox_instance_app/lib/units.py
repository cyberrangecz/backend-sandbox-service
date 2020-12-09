from typing import List

from kypo.openstack_driver import Event, Resource

from kypo.sandbox_common_lib import utils
from kypo.sandbox_instance_app.models import SandboxAllocationUnit


def get_stack_events(unit: SandboxAllocationUnit) -> List[Event]:
    """List all events in sandbox as Events objects."""
    stack_name = unit.get_stack_name()
    client = utils.get_ostack_client()
    # TODO get stack directly! throw exception
    if stack_name in client.list_stacks():
        return client.list_stack_events(stack_name)
    return []


def get_stack_resources(unit: SandboxAllocationUnit) -> List[Resource]:
    """List all resources in sandbox as Resource objects."""
    stack_name = unit.get_stack_name()
    client = utils.get_ostack_client()
    if stack_name in client.list_stacks():
        return client.list_stack_resources(stack_name)
    return []
