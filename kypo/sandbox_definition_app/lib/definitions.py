"""
Definition Service module for Definition management.
"""
import io
import structlog
from yamlize import YamlizingError
from django.conf import settings

from kypo.topology_definition.models import TopologyDefinition

from kypo.sandbox_definition_app import serializers
from kypo.sandbox_definition_app.models import Definition
from kypo.sandbox_definition_app.lib.definition_providers import GitlabProvider, GenericProvider
from kypo.sandbox_common_lib import utils, exceptions
from kypo.sandbox_common_lib.kypo_config import KypoConfiguration

LOG = structlog.get_logger()

SANDBOX_DEFINITION_FILENAME = 'sandbox.yml'


def create_definition(url: str, rev: str = None) -> Definition:
    """Validates and creates a new definition in database.

    :param url: URL of sandbox definition Git repository
    :param rev: Revision of the repository
    :return: New definition instance
    """
    top_def = get_definition(url, rev, settings.KYPO_CONFIG)

    client = utils.get_ostack_client()
    client.validate_sandbox_definition(top_def)
    if not GitlabProvider.has_key_access(url, settings.KYPO_CONFIG):
        raise exceptions.ValidationError('Repository is not accessible using SSH key.')

    serializer = serializers.DefinitionSerializerCreate(
        data=dict(name=top_def.name, url=url, rev=rev))
    serializer.is_valid(raise_exception=True)
    return serializer.save()


def get_definition(url: str, rev: str, config: KypoConfiguration) -> TopologyDefinition:
    """Get sandbox definition file content as TopologyDefinition.

    :param url: URL of sandbox definition Git repository
    :param rev: Revision of the repository
    :param config: KypoConfiguration
    :return: Topology definition
    :raise: GitError if GIT error occurs, ValidationError if definition is incorrect
    """
    try:
        if GenericProvider.is_local_repo(url):
            provider = GenericProvider(url, settings.KYPO_CONFIG.git_private_key)
        else:
            provider = GitlabProvider(url, config.git_access_token)
        definition = provider.get_file(rev, SANDBOX_DEFINITION_FILENAME)
    except exceptions.GitError as ex:
        raise exceptions.GitError("Failed to get sandbox definition file {}.\n"
                                  .format(SANDBOX_DEFINITION_FILENAME) + str(ex))
    try:
        return TopologyDefinition.load(io.StringIO(definition))
    except YamlizingError as ex:
        raise exceptions.ValidationError(ex)
