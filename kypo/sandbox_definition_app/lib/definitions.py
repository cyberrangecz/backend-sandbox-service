"""
Definition Service module for Definition management.
"""
import io

import structlog
import yaml
from django.conf import settings
from django.contrib.auth.models import User
from kypo.topology_definition.models import TopologyDefinition
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

    client = utils.get_terraform_client()
    client.validate_topology_definition(top_def)
    if not DefinitionProvider.has_key_access(url, settings.KYPO_CONFIG):
        raise exceptions.ValidationError('Repository is not accessible using SSH key.')

    serializer = serializers.DefinitionSerializerCreate(
        data=dict(name=top_def.name, url=url, rev=rev))
    serializer.is_valid(raise_exception=True)
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


def get_definition(url: str, rev: str, config: KypoConfiguration) -> TopologyDefinition:
    """Get sandbox definition file content as TopologyDefinition.

    :param url: URL of sandbox definition Git repository
    :param rev: Revision of the repository
    :param config: KypoConfiguration
    :return: Topology definition
    :raise: GitError if GIT error occurs, ValidationError if definition is incorrect
    """
    try:
        provider = get_def_provider(url, config)
        definition = provider.get_file(SANDBOX_DEFINITION_FILENAME, rev)
    except exceptions.GitError as ex:
        raise exceptions.GitError("Failed to get sandbox definition file {}.\n"
                                  .format(SANDBOX_DEFINITION_FILENAME) + str(ex))

    return load_definition(io.StringIO(definition))


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
