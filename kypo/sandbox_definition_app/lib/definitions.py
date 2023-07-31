"""
Definition Service module for Definition management.
"""
import io
import os

import structlog
import yaml
from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import caches
from kypo.topology_definition.models import TopologyDefinition, DockerContainers
from kypo.topology_definition.image_naming import image_name_replace
from yamlize import YamlizingError
from typing import Optional, TextIO

from generator.var_object import Variable
from kypo.sandbox_common_lib import utils, exceptions
from kypo.sandbox_common_lib.kypo_config import KypoConfiguration, GitType
from kypo.sandbox_definition_app import serializers
from kypo.sandbox_definition_app.lib.definition_providers import GitlabProvider, DefinitionProvider, InternalGitProvider
from kypo.sandbox_definition_app.models import Definition
from kypo.sandbox_ansible_app.lib.inventory import DefaultAnsibleHostsGroups

LOG = structlog.get_logger()

SANDBOX_DEFINITION_FILENAME = 'topology.yml'
DOCKER_CONTAINERS_FILENAME = 'containers.yml'
DOCKERFILE_FILENAME = 'Dockerfile'
VARIABLES_FILENAME = 'variables.yml'


def create_definition(url: str, created_by: Optional[User], rev: str = None) -> Definition:
    """Validates and creates a new definition in database.

    :param url: URL of sandbox definition Git repository
    :param created_by: User creating sandbox definition
    :param rev: Revision of the repository
    :return: New definition instance
    """
    top_def = get_definition(url, rev, settings.KYPO_CONFIG)
    validate_topology_definition(top_def)

    validate_docker_containers(url, rev, settings.KYPO_CONFIG)

    client = utils.get_terraform_client()
    client.validate_topology_definition(top_def)
    if not DefinitionProvider.has_key_access(url, settings.KYPO_CONFIG):
        raise exceptions.ValidationError('Repository is not accessible using SSH key.')

    serializer = serializers.DefinitionSerializerCreate(
        data=dict(name=top_def.name, url=url, rev=rev))
    if not serializer.is_valid():
        if str(serializer.errors).find("code='unique'") != -1:
            error_message = "Error: Definition with these parameters already exists"
        else:
            error_message = f"Unknown error: {serializer.errors}"

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
        raise exceptions.ValidationError(ex)

    image_naming_strategy = settings.KYPO_CONFIG.image_naming_strategy
    if image_naming_strategy:
        topology_definition = image_name_replace(image_naming_strategy.pattern,
                                                 image_naming_strategy.replace,
                                                 topology_definition)

    flavor_mapping = settings.KYPO_CONFIG.flavor_mapping
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
        raise exceptions.ValidationError(ex)
    return containers


def get_definition(url: str, rev: str, config: KypoConfiguration) -> TopologyDefinition:
    """Get sandbox definition file content as TopologyDefinition.

    :param url: URL of sandbox definition Git repository
    :param rev: Revision of the repository
    :param config: KypoConfiguration
    :return: Topology definition
    :raise: GitError if GIT error occurs, ValidationError if definition is incorrect
    """
    cache = caches['topology_cache']
    provider = get_def_provider(url, config)
    rev_sha = provider.get_rev_sha(rev)
    cache_key = f'definition-{url}-rev-sha-{rev_sha}-topology'
    top_def = cache.get(cache_key, None)
    if top_def is not None:
        return top_def

    try:
        definition = provider.get_file(SANDBOX_DEFINITION_FILENAME, rev_sha)
    except exceptions.GitError as ex:
        raise exceptions.GitError("Failed to get sandbox definition file {}.\n"
                                  .format(SANDBOX_DEFINITION_FILENAME) + str(ex))

    top_def = load_definition(io.StringIO(definition))
    cache.set(cache_key, top_def)
    return top_def


def get_containers(url: str, rev: str, config: KypoConfiguration) -> DockerContainers:
    """Get containers.yml file content as DockerContainers if the file exists, None otherwise.

    :param url: URL of sandbox definition Git repository
    :param rev: Revision of the repository
    :param config: KypoConfiguration
    :return: DockerContainers, None if not found
    """
    try:
        provider = get_def_provider(url, config)
        containers = provider.get_file(DOCKER_CONTAINERS_FILENAME, rev)
    except exceptions.GitError as ex:
        return None

    return load_docker_containers(io.StringIO(containers))


def get_dockerfile(url: str, rev: str, config: KypoConfiguration, path: str) -> str:
    """Det Dockerfile from the gitlab repository as string

    :param url: URL of sandbox definition Git repository
    :param rev: Revision of the repository
    :param config: KypoConfiguration
    :param path: Path to Dockerfile in the repository
    :return: Dockerfile as str
    :raise: GitError if GIT error occurs
    """
    provider = get_def_provider(url, config)
    return provider.get_file(os.path.join(path, DOCKERFILE_FILENAME), rev)


def get_variables(url: str, rev: str, config: KypoConfiguration) -> list:
    """Get APG variables file contents as an array of Variable object.

    :param url: URL of sandbox definition Git repository
    :param rev: Revision of the repository
    :param config: KypoConfiguration
    :return: array of Variables
    :raise: GitError if GIT error occurs
    """
    try:
        provider = get_def_provider(url, config)
        variables_file = provider.get_file(VARIABLES_FILENAME, rev)
    except exceptions.GitError as ex:
        raise exceptions.GitError("Unable to retrieve {} file from repository.\n"
                                  .format(VARIABLES_FILENAME) + str(ex))
    var_list = yaml.load(variables_file, Loader=yaml.FullLoader)

    variables = []
    for var in var_list.keys():
        v_name = var
        v_type = var_list[var]["type"]
        v_min = var_list[var].get("min")
        v_max = var_list[var].get("max")
        v_length = var_list[var].get("length")
        v_prohibited = var_list[var].get("prohibited")
        if v_prohibited is None:
            v_prohibited = []
        variables.append(Variable(v_name, v_type, v_min, v_max, v_prohibited, v_length))
    return variables


def get_def_provider(url: str, config: KypoConfiguration) -> DefinitionProvider:
    """Return correct provider according to the repository url."""
    if config.git_type == GitType.INTERNAL:
        return InternalGitProvider(url, config)
    if config.git_type == GitType.GITLAB:
        return GitlabProvider(url, config)
    raise exceptions.ImproperlyConfigured(f"Cannot determine provider type. provider_type={config.git_type}.")


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
            raise exceptions.ValidationError(f"Cannot redefine default KYPO ansible hosts groups."
                                             f" Colliding hosts group in topology definition:"
                                             f" '{group.name}'.")

    client = utils.get_terraform_client()
    terraform_flavors = client.get_flavors_dict()
    used_flavors = [host.flavor for host in topology_definition.hosts] +\
                   [router.flavor for router in topology_definition.routers]
    for flavor in used_flavors:
        if flavor not in terraform_flavors:
            raise exceptions.ValidationError(f"Flavor {flavor} was not found on the terraform "
                                             f"backend.")


def validate_docker_containers(url: str, rev: str, config: KypoConfiguration) -> None:
    """
    Validates docker containers in relation to themselves and the topology definition (ensures that
    container_mappings contains existing containers and hosts) and that each container has either an image
    or dockerfile path

    :param url: URL of sandbox definition Git repository
    :param rev: Revision of the repository
    :param config: KypoConfiguration
    :raise: GitError if GIT error occurs, Validation error if containers are misconfigured
    """
    topology_definition = get_definition(url, rev, config)
    containers = get_containers(url, rev, config)
    if not containers:
        return
    for container in containers.containers:
        if (not container.image and not container.dockerfile) or \
                (container.image and container.dockerfile):
            raise exceptions.ValidationError(f"Container {container.name} must have either image"
                                             f" or dockerfile specified.")
        if container.dockerfile:
            try:
                get_dockerfile(url, rev, config, container.dockerfile)
            except exceptions.GitError as ex:
                raise exceptions.ValidationError(
                    f"Container {container.name} contains invalid Dockerfile path. Error: {ex}")
        # TODO add check for the existence of the image
        # client = utils.get_terraform_client()
        # images = client.list_images()
    topdef_host_names = [host.name for host in topology_definition.hosts]
    container_names = [container.name for container in containers.containers]

    for container_mapping in containers.container_mappings:
        if container_mapping.container not in container_names:
            raise exceptions.ValidationError(f"Invalid docker container mappings in containers.yml."
                                             f" Container {container_mapping.container} is not"
                                             f" defined in containers section.")
        if container_mapping.host not in topdef_host_names:
            raise exceptions.ValidationError(f"Invalid docker container mappings in containers.yml."
                                             f" Host {container_mapping.host} does not exist.")

