"""
Simple utils module.
"""
import json
import logging
import time
import multiprocessing
import paramiko
import scp
import git
import os
import structlog
from Crypto.PublicKey import RSA
from typing import Tuple, Callable

from kypo2_openstack_lib.ostack_client import KypoOstackClient
from . import exceptions
from .config import config

# Create logger
LOG = structlog.get_logger()


def configure_logging() -> None:
    """Configure logging and structlog"""
    logging.basicConfig(level=config.LOG_LEVEL,
                        handlers=[logging.StreamHandler(), logging.FileHandler(config.LOG_FILE)],
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


def get_scp_client(server: str, username: str, key_filename: str,
                   timeout: int = 30) -> scp.SCPClient:
    """
    Get scp client. Call `close` method after you finish.

    :param server: Server IP
    :param username: Username
    :param key_filename: Private key filename
    :param timeout: Optional timeout parameter
    :return: SCP client
    """
    ssh_client = paramiko.SSHClient()
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh_client.connect(server, username=username, key_filename=key_filename, timeout=timeout)

    return scp.SCPClient(ssh_client.get_transport())


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
    return KypoOstackClient(**config.OS_CREDENTIALS)


def wait_for(cond: Callable, timeout: int, freq: int, factor: float = 1.1, initial_wait: int = 0,
             errmsg: str = "") -> None:
    """ Wait until `cond` returns True or timeout seconds.
    The time spent by condition check is not included.
    raises: LimitExceededError: on timeout with errmsg
    """
    time.sleep(initial_wait)
    elapsed = initial_wait

    while not cond():
        elapsed += freq
        if elapsed > timeout:
            raise exceptions.LimitExceededError(errmsg)
        time.sleep(int(freq))
        freq *= factor


class GitRepo:
    lock = multiprocessing.Lock()

    @classmethod
    def get_git_repo(cls, url: str, rev: str) -> git.Repo:
        """
        Clone remote repository or retrieve its local copy and checkout revision.

        :param url: URL of remote Git repository
        :param rev: Revision of the repository
        :return: Git Repo object
        :raise: git.exc.GitCommandError if the revision is unknown to Git
        """
        with cls.lock:
            git_ssh_cmd = 'ssh -o StrictHostKeyChecking=no -i {0}'.format(config.GIT_PRIVATE_KEY)
            local_repository = os.path.join(config.GIT_REPOSITORIES, url, rev).replace(":", "")

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
            except git.exc.GitCommandError:
                pass

            return repo


def ssh_connection(server: str, username: str, cmd: str, key_path: str, proxy: str = None,
                   proxy_username: str = None, timeout: int = 30, raise_on_error=False)\
        -> Tuple[int, str, str]:
    """
    Creates ssh connection to server and executes given command on server.
    If raise_on_error set to True, then raises `NetworkError` if exit code is not 0.

    return: Tuple of (exit code, stdout, stderr)
    """
    port = 22
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    if proxy:
        proxy_client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        proxy_client.connect(proxy, username=proxy_username, key_filename=key_path, timeout=timeout,
                             banner_timeout=timeout, auth_timeout=timeout)

        dst_addr = (server, port)
        src_addr = (proxy, port)
        transport = client.get_transport()
        channel = transport.open_channel("direct-tcpip", dst_addr, src_addr)

        client.connect(server, username=username, key_filename=key_path, timeout=timeout,
                       sock=channel, banner_timeout=timeout, auth_timeout=timeout)
    else:
        client.connect(server, username=username, key_filename=key_path, timeout=timeout,
                       banner_timeout=timeout, auth_timeout=timeout)

    stdin, stdout, stderr = client.exec_command(cmd)

    out = stdout.read().decode()
    exit_code = stdout.channel.recv_exit_status()
    err = stderr.read().decode()

    client.close()

    if raise_on_error and exit_code != 0:
        raise exceptions.NetworkError("Command {} returned exitcode {}; stdout: {}, stderr: {}".
                                      format(cmd, exit_code, out, err))
    return exit_code, out, err
