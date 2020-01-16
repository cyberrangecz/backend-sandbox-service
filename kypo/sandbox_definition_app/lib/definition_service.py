"""
Definition Service module for Definition management.
"""
import structlog
import yaml
from git.exc import GitCommandError
from typing import Optional

from ..sandbox_common import utils, exceptions
from ..sandbox_common.config import config
from . import serializers
from .models import Definition

LOG = structlog.get_logger()


def create_definition(url: str, rev: str = None) -> Definition:
    """Validates and creates a new definition in database.

    :param url: URL of sandbox definition Git repository
    :param rev: Revision of the repository
    :return: New definition instance
    """
    sandbox_definition = get_sandbox_definition(url, rev)

    client = utils.get_ostack_client()
    client.validate_sandbox_definition(sandbox_definition)

    parsed_sandbox_definition = yaml.full_load(sandbox_definition)
    serializer = serializers.DefinitionSerializerCreate(
        data=dict(name=parsed_sandbox_definition['name'], url=url, rev=rev))
    serializer.is_valid(raise_exception=True)
    return serializer.save()


def get_sandbox_definition(url: str, rev: str, name: Optional[str] = None) -> str:
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
        definition = repo.git.show('{0}:{1}'.format(rev, config.SANDBOX_DEFINITION_FILENAME))
    except GitCommandError as ex:
        raise exceptions.GitError("Failed to get sandbox definition file {}.\n"
                                  .format(config.SANDBOX_DEFINITION_FILENAME) + str(ex))
    return definition
