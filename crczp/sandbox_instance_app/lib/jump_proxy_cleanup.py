import structlog
import paramiko
import time

from crczp.sandbox_instance_app.models import SandboxAllocationUnit
from django.conf import settings


LOG = structlog.get_logger()

# Retry when jump proxy is temporarily unreachable (e.g. overload)
DELETE_JUMP_SSH_KEY_RETRIES = 5
DELETE_JUMP_SSH_KEY_RETRY_DELAY_SEC = 1


def delete_jump_ssh_key(allocation_unit: SandboxAllocationUnit):
    """Remove SSH key directory for this allocation from the jump proxy. Retries up to
    DELETE_JUMP_SSH_KEY_RETRIES times with DELETE_JUMP_SSH_KEY_RETRY_DELAY_SEC delay on
    connection errors (e.g. jump host overload).
    """
    name = allocation_unit.get_stack_name()
    last_exc = None
    for attempt in range(1, DELETE_JUMP_SSH_KEY_RETRIES + 1):
        try:
            ssh = connect_to_jump()
            try:
                stdin, stdout, stderr = ssh.exec_command(f"sudo rm -rf /home/{name}")
                stdout.channel.recv_exit_status()
                error = stderr.read().decode()
                if error:
                    LOG.warning("failed_to_delete_key_from_proxy", stack_name=name, error=error)
            finally:
                ssh.close()
            return
        except (paramiko.ssh_exception.NoValidConnectionsError, OSError, ConnectionError) as e:
            last_exc = e
            if attempt < DELETE_JUMP_SSH_KEY_RETRIES:
                LOG.warning(
                    "jump_proxy_connection_failed_retrying",
                    attempt=attempt,
                    max_retries=DELETE_JUMP_SSH_KEY_RETRIES,
                    delay_sec=DELETE_JUMP_SSH_KEY_RETRY_DELAY_SEC,
                    error=str(e),
                )
                time.sleep(DELETE_JUMP_SSH_KEY_RETRY_DELAY_SEC)
            else:
                LOG.warning(
                    "jump_proxy_connection_failed_after_retries",
                    attempt=attempt,
                    error=str(e),
                )
    if last_exc is not None:
        raise last_exc


def connect_to_jump():
    hostname = settings.CRCZP_CONFIG.proxy_jump_to_man.Host
    user = settings.CRCZP_CONFIG.proxy_jump_to_man.User
    identity_file = settings.CRCZP_CONFIG.proxy_jump_to_man.IdentityFile
    port = settings.CRCZP_CONFIG.proxy_jump_to_man.Port

    return ssh_connect(hostname, port, user, identity_file)


def ssh_connect(hostname, port, username, key_file_path):
    try:
        ssh = paramiko.SSHClient()
        ssh.load_system_host_keys()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        private_key = load_private_key(key_file_path)

        ssh.connect(hostname, port=port, username=username, pkey=private_key)
        return ssh
    except Exception as e:
        LOG.warning(f"Failed to connect to {hostname}: {e}")
        raise


def load_private_key(key_path):
    key_classes = [paramiko.RSAKey, paramiko.ECDSAKey, paramiko.Ed25519Key]
    for key_class in key_classes:
        try:
            return key_class.from_private_key_file(key_path)
        except (paramiko.SSHException, IOError):
            continue
    raise ValueError("Could not load private key. Unsupported key type or file not found.")
