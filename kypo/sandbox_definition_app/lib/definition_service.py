"""
Definition Service module for Definition management.
"""
from typing import Optional
import io
import structlog
from git.exc import GitCommandError
from yamlize import YamlizingError

from kypo.topology_definition.models import TopologyDefinition

from .. import serializers
from ..models import Definition
from ...sandbox_common_lib import utils, exceptions

LOG = structlog.get_logger()

SANDBOX_DEFINITION_FILENAME = 'sandbox.yml'


def create_definition(url: str, rev: str = None) -> Definition:
    """Validates and creates a new definition in database.

    :param url: URL of sandbox definition Git repository
    :param rev: Revision of the repository
    :return: New definition instance
    """
    top_def = get_definition(url, rev)

    client = utils.get_ostack_client()
    client.validate_sandbox_definition(top_def)

    serializer = serializers.DefinitionSerializerCreate(
        data=dict(name=top_def.name, url=url, rev=rev))
    serializer.is_valid(raise_exception=True)
    return serializer.save()


def get_definition(url: str, rev: str, name: Optional[str] = None) -> TopologyDefinition:
    """
    Get sandbox definition file content

    :param url: URL of sandbox definition Git repository
    :param rev: Revision of the repository
    :param name: The optional name of local repository
    :return: Content of sandbox definition
    :raise: git.exc.GitCommandError if revision is unknown to Git
        or sandbox definition does not exist under this revision
    """
    try:
        repo = utils.GitRepo.get_git_repo(url, rev, name)
        definition = repo.git.show('{0}:{1}'.format(rev, SANDBOX_DEFINITION_FILENAME))
    except GitCommandError as ex:
        raise exceptions.GitError("Failed to get sandbox definition file {}.\n"
                                  .format(SANDBOX_DEFINITION_FILENAME) + str(ex))
    try:
        return TopologyDefinition.load(io.StringIO(definition))
    except YamlizingError as ex:
        raise exceptions.ValidationError(ex)
