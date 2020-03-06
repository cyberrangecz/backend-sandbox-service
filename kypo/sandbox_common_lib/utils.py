"""
Simple utils module.
"""
import json
import logging
import multiprocessing
import os
import re
import uuid
from typing import Tuple, Optional
import git
import structlog
from Crypto.PublicKey import RSA
from kypo.openstack_driver.ostack_client import KypoOstackClient
from django.conf import settings

# Create logger
LOG = structlog.get_logger()


def configure_logging() -> None:
    """Configure logging and structlog"""
    # noinspection PyArgumentList
    logging.basicConfig(level=settings.KYPO_CONFIG.log_level,
                        handlers=[logging.StreamHandler(),
                                  logging.FileHandler(settings.KYPO_CONFIG.log_file)],
                        format="%(message)s")
    structlog.configure(
        processors=[
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=False),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.dev.ConsoleRenderer(),  # (colors=False) to decolorise
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    LOG.info("Logging is set and ready to use.")


def json_pretty_print(data: dict) -> str:
    """
    Pretty print JSON as string. Used primarily for logging purposes.
    :param data: Mapping type of JSON
    :return: JSON string
    """
    return json.dumps(data, indent=2)


def generate_ssh_keypair(bits: int = 2048) -> Tuple[str, str]:
    """
    Generate SSH-RSA key pair.

    :return: Tuple of private and public key strings
    """
    key = RSA.generate(bits)
    priv_key = key.exportKey().decode()
    pub_key = key.publickey().exportKey("OpenSSH").decode()
    return priv_key, pub_key


def get_ostack_client() -> KypoOstackClient:
    """Abstracts creation and authentication to KYPO lib client."""
    return KypoOstackClient(app_creds_id=settings.KYPO_CONFIG.os_application_credential_id,
                            auth_url=settings.KYPO_CONFIG.os_auth_url,
                            app_creds_secret=settings.KYPO_CONFIG.os_application_credential_secret,
                            trc=settings.KYPO_CONFIG.trc)


def get_simple_uuid() -> str:
    """First four bytes of UUID as string."""
    return str(uuid.uuid4()).split('-')[0]


class GitRepo:
    GIT_REPOSITORIES = '/tmp'
    lock = multiprocessing.Lock()

    @classmethod
    def get_git_repo(cls, url: str, rev: str, name: Optional[str] = None) -> git.Repo:
        """
        Clone remote repository or retrieve its local copy and checkout revision.

        :param url: URL of remote Git repository
        :param rev: Revision of the repository
        :param name: The optional name of local repository
        :return: Git Repo object
        :raise: git.exc.GitCommandError if the revision is unknown to Git
        """
        with cls.lock:
            git_ssh_cmd = 'ssh -o StrictHostKeyChecking=no -i {0}'\
                .format(settings.KYPO_CONFIG.git_private_key)
            local_repository = os.path.join(cls.GIT_REPOSITORIES,
                                            url, name if name else rev).replace(":", "")

            if os.path.isdir(local_repository):
                repo = git.Repo(local_repository)
            else:
                os.makedirs(local_repository, exist_ok=True)
                repo = git.Repo.clone_from(url, local_repository, env={'GIT_SSH_COMMAND': git_ssh_cmd})
                repo.git.checkout(rev)
            try:
                # check if revision is branch
                repo.git.show_ref('--verify', 'refs/heads/{0}'.format(rev))
                repo.remote().pull(env={'GIT_SSH_COMMAND': git_ssh_cmd})
            except git.exc.GitCommandError as ex:
                LOG.warning("Git pull failed", exception=str(ex))
                pass

            return repo

    @staticmethod
    def is_local_repo(url: str) -> bool:
        return url.startswith('file://')

    @staticmethod
    def local_repo_path(url: str) -> str:
        return re.sub('^file://', '', url)


class AttrDict(dict):
    def __init__(self, *args, **kwargs):
        super(AttrDict, self).__init__(*args, **kwargs)
        self.__dict__ = self
