"""
Definition Service module for Definition management.
"""

import io
import os
from ipaddress import ip_address
from typing import TextIO

import structlog
import yaml
from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import caches
from generator.var_object import Variable
from yamlize import YamlizingError

from crczp.cloud_commons import CrczpException
from crczp.openstack_driver.network_forwarding import router_interface_ip
from crczp.sandbox_ansible_app.lib.inventory import DefaultAnsibleHostsGroups
from crczp.sandbox_common_lib import exceptions, git_config, utils
from crczp.sandbox_common_lib.common_cloud import list_images
from crczp.sandbox_common_lib.crczp_config import CrczpConfiguration, GitType, TopologyCacheMode
from crczp.sandbox_definition_app import serializers
from crczp.sandbox_definition_app.lib.definition_providers import (
    DefinitionProvider,
    GitHubProvider,
    GitlabProvider,
)
from crczp.sandbox_definition_app.models import Definition
from crczp.topology_definition.image_naming import image_name_replace
from crczp.topology_definition.models import DockerContainers, TopologyDefinition

LOG = structlog.get_logger()

SANDBOX_DEFINITION_FILENAME = 'topology.yml'
DOCKER_CONTAINERS_FILENAME = 'containers.yml'
DOCKERFILE_FILENAME = 'Dockerfile'
VARIABLES_FILENAME = 'variables.yml'


def create_definition(url: str, created_by: User | None, rev: str = 'master') -> Definition:
    """Validates and creates a new definition in database.

    :param url: URL of sandbox definition Git repository
    :param created_by: User creating sandbox definition
    :param rev: Revision of the repository
    :return: New definition instance
    """
    force_refresh = (
        git_config.get_git_type(url) == GitType.GITHUB
        and settings.CRCZP_CONFIG.topology_cache_mode is TopologyCacheMode.FRESH_IMPORT
    )
    top_def = get_definition(url, rev, settings.CRCZP_CONFIG, force_refresh=force_refresh)
    validate_topology_definition(top_def)
    validate_docker_containers(url, rev, settings.CRCZP_CONFIG)

    client = utils.get_terraform_client()
    client.validate_topology_definition(top_def)

    serializer = serializers.DefinitionSerializerCreate(
        data={'name': top_def.name, 'url': url, 'rev': rev}
    )
    if not serializer.is_valid():
        if str(serializer.errors).find("code='unique'") != -1:
            error_message = 'Error: Definition with these parameters already exists'
        else:
            error_message = f'Unknown error: {serializer.errors}'

        raise exceptions.ValidationError(error_message)
    return serializer.save(created_by=created_by)


def load_definition(stream: TextIO) -> TopologyDefinition:
    """Load TopologyDefinition from opened stream and make appropriate transformation.

    :param stream: The opened stream from which the TopologyDefinition will be loaded
    :raise: ValidationError if the TopologyDefinition cannot be loaded
    """
    try:
        topology_definition = TopologyDefinition.load(stream)
    except YamlizingError as ex:
        raise exceptions.ValidationError(ex) from ex

    image_naming_strategy = settings.CRCZP_CONFIG.image_naming_strategy
    if image_naming_strategy:
        topology_definition = image_name_replace(
            image_naming_strategy.pattern, image_naming_strategy.replace, topology_definition
        )

    flavor_mapping = settings.CRCZP_CONFIG.flavor_mapping
    if flavor_mapping:
        for host in topology_definition.hosts:
            if host.flavor in flavor_mapping:
                host.flavor = flavor_mapping[host.flavor]
        for router in topology_definition.routers:
            if router.flavor in flavor_mapping:
                router.flavor = flavor_mapping[router.flavor]

    return topology_definition


def load_docker_containers(stream: TextIO) -> DockerContainers:
    """Load DockerContainers from opened stream and make appropriate transformation.

    :param stream: The opened stream from which the DockerContainers will be loaded
    :raise: ValidationError if the DockerContainers cannot be loaded
    """
    try:
        containers = DockerContainers.load(stream)
    except YamlizingError as ex:
        raise exceptions.ValidationError(ex) from ex
    return containers


def get_definition(
    url: str, rev: str, config: CrczpConfiguration, *, force_refresh: bool = False
) -> TopologyDefinition:
    """Get sandbox definition file content as TopologyDefinition.

    :param url: URL of sandbox definition Git repository
    :param rev: Revision of the repository
    :param config: CrczpConfiguration
    :param force_refresh: Skip the cache read and fetch fresh, still refreshing the cache entry
    :return: Topology definition
    :raise: GitError if GIT error occurs, ValidationError if definition is incorrect
    """
    cache = caches['topology_cache']
    provider = get_def_provider(url, config)
    rev_sha = provider.get_rev_sha(rev)
    cache_key = f'definition-{url}-rev-sha-{rev_sha}-topology'
    if not force_refresh:
        top_def = cache.get(cache_key, None)
        if top_def is not None:
            return top_def

    try:
        definition = provider.get_file(SANDBOX_DEFINITION_FILENAME, rev_sha)
    except exceptions.GitError as ex:
        raise exceptions.GitError(
            f'Failed to get sandbox definition file {SANDBOX_DEFINITION_FILENAME}.\n' + str(ex)
        ) from ex

    top_def = load_definition(io.StringIO(definition))
    validate_topology_definition(top_def)
    cache.set(cache_key, top_def)
    return top_def


def get_containers(url: str, rev: str, config: CrczpConfiguration) -> DockerContainers:
    """Get containers.yml file content as DockerContainers if the file exists, None otherwise.

    :param url: URL of sandbox definition Git repository
    :param rev: Revision of the repository
    :param config: CrczpConfiguration
    :return: DockerContainers, None if not found
    """
    try:
        provider = get_def_provider(url, config)
        containers = provider.get_file(DOCKER_CONTAINERS_FILENAME, rev)
    except exceptions.GitError:
        return None

    return load_docker_containers(io.StringIO(containers))


def get_dockerfile(url: str, rev: str, config: CrczpConfiguration, path: str) -> str:
    """Det Dockerfile from the gitlab repository as string

    :param url: URL of sandbox definition Git repository
    :param rev: Revision of the repository
    :param config: CrczpConfiguration
    :param path: Path to Dockerfile in the repository
    :return: Dockerfile as str
    :raise: GitError if GIT error occurs
    """
    provider = get_def_provider(url, config)
    return provider.get_file(os.path.join(path, DOCKERFILE_FILENAME), rev)


def get_variables(url: str, rev: str, config: CrczpConfiguration) -> list[Variable]:
    """Get APG variables file contents as an array of Variable object.

    :param url: URL of sandbox definition Git repository
    :param rev: Revision of the repository
    :param config: CrczpConfiguration
    :return: array of Variables
    :raise: GitError if GIT error occurs
    """
    try:
        provider = get_def_provider(url, config)
        variables_file = provider.get_file(VARIABLES_FILENAME, rev)
    except exceptions.GitError as ex:
        raise exceptions.GitError(
            f'Unable to retrieve {VARIABLES_FILENAME} file from repository.\n' + str(ex)
        ) from ex
    var_list = yaml.safe_load(variables_file)

    variables = []
    for var in var_list:
        v_name = var
        v_type = var_list[var]['type']
        v_min = var_list[var].get('min')
        v_max = var_list[var].get('max')
        v_length = var_list[var].get('length')
        v_prohibited = var_list[var].get('prohibited')
        if v_prohibited is None:
            v_prohibited = []
        variables.append(Variable(v_name, v_type, v_min, v_max, v_prohibited, v_length))
    return variables


def get_def_provider(url: str, config: CrczpConfiguration) -> DefinitionProvider:
    """Return correct provider according to the repository url."""
    git_type = git_config.get_git_type(url)
    if git_type == GitType.GITLAB:
        return GitlabProvider(url, config)
    if git_type == GitType.GITHUB:
        return GitHubProvider(url, config)
    raise exceptions.ImproperlyConfigured(
        f'Cannot determine provider type: {git_config.get_rest_server(url)} '
        f'Supported types: gitlab, github'
    )


def validate_topology_definition(topology_definition: TopologyDefinition) -> None:
    """
    Validates ansible hosts groups of topology definition

    :param topology_definition: Topology definition
    :raise: ValidationError if definition is incorrect
    """
    user_defined_hosts_groups = topology_definition.groups
    default_hosts_groups = [group.value for group in DefaultAnsibleHostsGroups.__members__.values()]

    for group in user_defined_hosts_groups:
        if group.name in default_hosts_groups:
            raise exceptions.ValidationError(
                f'Cannot redefine default CRCZP ansible hosts groups.'
                f' Colliding hosts group in topology definition:'
                f" '{group.name}'."
            )

    if getattr(topology_definition, 'network_forwarding', None):
        if not getattr(settings.CRCZP_CONFIG, 'network_forwarding_enabled', False):
            raise exceptions.ValidationError(
                'This sandbox definition declares network_forwarding (traffic mirroring), but the '
                'feature is not enabled on this deployment. Set '
                'application_configuration.network_forwarding_enabled to True (requires OVN/TaaS '
                'on OpenStack or VPC Traffic Mirroring on AWS).'
            )
        if not settings.AWS_PROVIDER_CONFIGURED and not getattr(
            getattr(settings.CRCZP_CONFIG, 'openstack', None), 'hypervisor_cidr', None
        ):
            raise exceptions.ValidationError(
                'This sandbox definition declares network_forwarding (traffic mirroring), which '
                'exposes each mirror destination on a floating IP. Set '
                'application_configuration.openstack.hypervisor_cidr to the CIDR the hypervisors '
                'send the mirrored traffic from; it is the only source allowed to reach that '
                'floating IP.'
            )
        if not settings.AWS_PROVIDER_CONFIGURED:
            _validate_forwarding_reserved_addresses(topology_definition)

    client = utils.get_terraform_client()
    terraform_flavors = client.get_flavors_dict()
    terraform_images = [image.name for image in list_images()]

    used_flavors = [host.flavor for host in topology_definition.hosts] + [
        router.flavor for router in topology_definition.routers
    ]

    used_images = [host.base_box.image for host in topology_definition.hosts] + [
        router.base_box.image for router in topology_definition.routers
    ]

    for flavor in used_flavors:
        if flavor not in terraform_flavors:
            raise exceptions.ValidationError(
                f'Flavor {flavor} was not found on the terraform backend.'
            )

    for image in used_images:
        if image not in terraform_images:
            raise exceptions.ValidationError(
                f'Image {image} was not found on the terraform backend.'
            )


def _validate_forwarding_reserved_addresses(topology_definition: TopologyDefinition) -> None:
    """
    Validates no mapping claims an address OpenStack reserves on the mirror-destination network.

    The OpenStack driver pins the router interface that exposes the mirror destination to a fixed
    address of the destination network. Nothing in the topology schema reserves it, so this check
    reports the clash while the definition is being registered rather than letting it surface as a
    Neutron error part-way through a sandbox build.

    :param topology_definition: Topology definition
    :raise: ValidationError if a mapping claims the reserved address, or the destination network is
        too small to spare one
    """
    networks = {network.name: network.cidr for network in topology_definition.networks}
    network_name = topology_definition.network_forwarding.destination.network
    cidr = networks.get(network_name)
    if cidr is None:
        return  # An unknown network is already reported by the schema validators.
    try:
        reserved = ip_address(router_interface_ip(network_name, cidr))
    except CrczpException as exc:
        raise exceptions.ValidationError(str(exc)) from exc

    mappings = [
        (mapping.host, mapping.network, mapping.ip) for mapping in topology_definition.net_mappings
    ] + [
        (mapping.router, mapping.network, mapping.ip)
        for mapping in topology_definition.router_mappings
    ]

    for node_name, mapped_network, mapped_ip in mappings:
        if mapped_network == network_name and ip_address(mapped_ip) == reserved:
            raise exceptions.ValidationError(
                f'Network "{network_name}" ({cidr}) is the network_forwarding destination, so '
                f'{reserved} is reserved for the router interface that exposes the mirror '
                f'destination on a floating IP, but "{node_name}" is mapped to it. The first '
                'three addresses of such a network belong to the platform: the network '
                f'address, the router, and DHCP. Assign "{node_name}" a higher address.'
            )


def validate_docker_containers(url: str, rev: str, config: CrczpConfiguration) -> None:
    """
    Validates docker containers in relation to themselves and the topology definition (ensures that
    container_mappings contains existing containers and hosts) and that each container has either
    an image or dockerfile path

    :param url: URL of sandbox definition Git repository
    :param rev: Revision of the repository
    :param config: CrczpConfiguration
    :raise: GitError if GIT error occurs, Validation error if containers are misconfigured
    """
    topology_definition = get_definition(url, rev, config)
    containers = get_containers(url, rev, config)
    if not containers:
        return
    for container in containers.containers:
        if (not container.image and not container.dockerfile) or (
            container.image and container.dockerfile
        ):
            raise exceptions.ValidationError(
                f'Container {container.name} must have either image or dockerfile specified.'
            )
        if container.dockerfile:
            try:
                get_dockerfile(url, rev, config, container.dockerfile)
            except exceptions.GitError as ex:
                raise exceptions.ValidationError(
                    f'Container {container.name} contains invalid Dockerfile path. Error: {ex}'
                ) from ex
        # Note: image existence check not yet implemented
        # client = utils.get_terraform_client()
        # images = client.list_images()
    topdef_host_names = [host.name for host in topology_definition.hosts]
    container_names = [container.name for container in containers.containers]

    for container_mapping in containers.container_mappings:
        if container_mapping.container not in container_names:
            raise exceptions.ValidationError(
                f'Invalid docker container mappings in containers.yml.'
                f' Container {container_mapping.container} is not'
                f' defined in containers section.'
            )
        if container_mapping.host not in topdef_host_names:
            raise exceptions.ValidationError(
                f'Invalid docker container mappings in containers.yml.'
                f' Host {container_mapping.host} does not exist.'
            )
