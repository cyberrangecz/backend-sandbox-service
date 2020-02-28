from typing import List

from kypo.openstack_driver.stack import Event, Resource

from kypo.sandbox_common_lib import utils


def get_stack_events(stack_name: str) -> List[Event]:
    """List all events in sandbox as Events objects."""
    client = utils.get_ostack_client()
    if stack_name in client.list_sandboxes():
        return client.list_sandbox_events(stack_name)
    return []


def get_stack_resources(stack_name: str) -> List[Resource]:
    """List all resources in sandbox as Resource objects."""
    client = utils.get_ostack_client()
    if stack_name in client.list_sandboxes():
        return client.list_sandbox_resources(stack_name)
    return []