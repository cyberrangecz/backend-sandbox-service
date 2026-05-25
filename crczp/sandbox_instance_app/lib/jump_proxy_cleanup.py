"""Utilities for cleaning up resources on the jump proxy host."""

import paramiko
import structlog
from django.conf import settings
from paramiko import PKey, SSHClient

from crczp.sandbox_instance_app.models import SandboxAllocationUnit

LOG = structlog.get_logger()


def delete_jump_ssh_key(allocation_unit: SandboxAllocationUnit) -> None:
    """Delete the SSH key for the given allocation unit from the jump proxy."""
    name = allocation_unit.get_stack_name()
    ssh = connect_to_jump()
    _stdin, stdout, stderr = ssh.exec_command(f'sudo rm -rf /home/{name}')  # nosec B601

    # Wait for the command to finish
    stdout.channel.recv_exit_status()
    error = stderr.read().decode()
    if error:
        LOG.warning(f'Failed to delete key for {name} from proxy jump: {error}')


def connect_to_jump() -> SSHClient:
    """Establish an SSH connection to the configured jump proxy host."""
    hostname = settings.CRCZP_CONFIG.proxy_jump_to_man.Host
    user = settings.CRCZP_CONFIG.proxy_jump_to_man.User
    identity_file = settings.CRCZP_CONFIG.proxy_jump_to_man.IdentityFile
    port = settings.CRCZP_CONFIG.proxy_jump_to_man.Port

    return ssh_connect(hostname, port, user, identity_file)


def ssh_connect(hostname: str, port: int, username: str, key_file_path: str) -> SSHClient:
    """Create and return an authenticated SSH connection."""
    try:
        ssh = paramiko.SSHClient()
        ssh.load_system_host_keys()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # nosec B507
        private_key = load_private_key(key_file_path)

        ssh.connect(hostname, port=port, username=username, pkey=private_key)
        return ssh
    except Exception as e:
        LOG.warning(f'Failed to connect to {hostname}: {e}')
        raise


def load_private_key(key_path: str) -> PKey:
    """Load and return a Paramiko private key from the given file path."""
    key_classes = [paramiko.RSAKey, paramiko.ECDSAKey, paramiko.Ed25519Key]
    for key_class in key_classes:
        try:
            return key_class.from_private_key_file(  # type: ignore[attr-defined, no-any-return]
                key_path
            )
        except (OSError, paramiko.SSHException):
            continue
    raise ValueError('Could not load private key. Unsupported key type or file not found.')
