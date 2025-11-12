"""
VM Service module for VM management.
"""
import itertools

import django_rq
from crczp.cloud_commons import TopologyInstance, Image
from crczp.cloud_commons.topology_elements import Node
from crczp.terraform_driver import TerraformInstance
from django.conf import settings
from django.core.cache import cache

from crczp.sandbox_common_lib import utils, exceptions
from crczp.sandbox_common_lib.common_cloud import list_images
from crczp.sandbox_instance_app.models import Sandbox

CACHE_CONSOLE_PREFIX = "console-"
CACHE_CONSOLE_TIMEOUT = 7200  # the console URLs can last for about 2-3 hours
CACHE_JOB_WORKER_TIME = 300

class Protocol(object):
    """Represents a protocol used to access a node.
    Attributes:
        name (str): Name of the protocol (e.g., 'SSH', 'RDP', 'VNC').
        port (int): Port at which the protocol is listening.
    """
    def __init__(self, name: str, port: int):
        self.name = name
        self.port = port

    @classmethod
    def ssh(cls):
        return cls('SSH', 22)

    @classmethod
    def rdp(cls):
        return cls('RDP', 3389)

    @classmethod
    def vnc(cls):
        return cls('VNC', 5900)


class NodeAccessData(object):
    """Holds data necessary to remotely access a node in a sandbox.

    Attributes:
        man_ip (str): Management IP address of the sandbox.
        man_port (int): Management port of the sandbox.
        host_ip (str): Host IP address of the machine inside the sandbox.
        protocols (list[Protocol]): List of allowed protocols for node access.
    """

    def __init__(
            self,
            man_ip: str,
            man_port: int,
            host_ip: str,
            protocols: list[Protocol]):
        self.man_ip = man_ip
        self.man_port = man_port
        self.host_ip = host_ip
        self.protocols = protocols


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


def get_console_url_job(stack_name, node_name, console_type, console_cache_name,
                        job_cache_id_running):
    client = utils.get_terraform_client()
    console_url = client.get_console_url(stack_name, node_name, console_type)
    cache.set(console_cache_name, console_url, CACHE_CONSOLE_TIMEOUT)
    cache.delete(job_cache_id_running)


def get_console_url(sandbox: Sandbox, node_name: str) -> str:
    """Get console URL for given VM."""
    console_cache_name = CACHE_CONSOLE_PREFIX + str(sandbox.id) + '-' + node_name
    job_cache_id_running = CACHE_CONSOLE_PREFIX + str(sandbox.id) + '-' + node_name + '-running'
    console_url = cache.get(console_cache_name, None)
    if console_url:
        return console_url

    job_running = cache.get(job_cache_id_running, False)
    if not job_running:
        cache.set(job_cache_id_running, True, CACHE_JOB_WORKER_TIME)
        django_rq.enqueue(get_console_url_job, sandbox.allocation_unit.get_stack_name(),
                          node_name, settings.CRCZP_CONFIG.os_console_type.value, console_cache_name,
                          job_cache_id_running)
    return ""


def get_node_access_data(topology_instance: TopologyInstance, node: Node) -> NodeAccessData:
    if topology_instance is None:
        raise exceptions.ValidationError("Topology instance is None")
    if node is None:
        raise exceptions.ValidationError(f"Node is None in topology instance {topology_instance.name}")

    return NodeAccessData(
        man_ip=topology_instance.ip,
        man_port=settings.CRCZP_CONFIG.man_port,
        host_ip=_get_node_ip(topology_instance, node),
        protocols=get_node_available_protocols(node),
    )


def find_image_for_node(node: Node, images=None) -> Image:
    """
    Find the image for a given node.

    :param node: The node object
    :param images: List of available images
    :type images: list
    :return: The matching image object or None if not found
    """
    if images is None:
        images = list_images()
    for image in images:
        if image.name == node.base_box.image:
            return image

    raise exceptions.ValidationError(f"No image found for node {node.name}")


def get_node_available_protocols(node: Node) -> list[Protocol]:
    image = find_image_for_node(node)
    protocols = [Protocol.ssh()]
    if get_node_image_has_gui_access(image):
        if image.os_type == 'linux':
            protocols.append(Protocol.vnc())
        else:
            protocols.append(Protocol.rdp())
    return protocols


def get_node_image_has_gui_access(image: Image) -> bool:
    return image.owner_specified.get('owner_specified.openstack.gui_access') == 'true'


def _get_node_ip(topology_instance: TopologyInstance, node: Node) -> str:
    """Get the IP address of a node from the topology instance."""
    host_links = topology_instance.get_node_links(node, topology_instance.get_hosts_networks())
    router_links = topology_instance.get_node_links(node, [topology_instance.wan])

    for link in itertools.chain(router_links, host_links):
        network = link.network
        if hasattr(network, 'accessible_by_user') and network.accessible_by_user is not None and not network.accessible_by_user:
            raise exceptions.ValidationError(f"Node {node.name} is not user-accessible")
        if link.ip:
            return link.ip

    raise exceptions.ValidationError(f"No accessible IP found for node {node.name}")
