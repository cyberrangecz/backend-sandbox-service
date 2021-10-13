import os
import shutil

import docker
import structlog
from django.conf import settings
from docker.models.containers import Container

from kypo.sandbox_ansible_app.lib.inventory import Inventory, BaseInventory, KYPO_PROXY_JUMP_NAME
from kypo.sandbox_common_lib import exceptions
from kypo.sandbox_instance_app.lib import sandboxes, sshconfig
from kypo.sandbox_instance_app.models import Sandbox, Pool, SandboxAllocationUnit

LOG = structlog.get_logger()


class DockerVolume:
    def __init__(self, bind: str, mode: str):
        self.bind = bind
        self.mode = mode


ANSIBLE_INVENTORY_FILENAME = 'inventory.yml'
MGMT_PRIVATE_KEY_FILENAME = 'pool_mng_key'
MGMT_CERTIFICATE_FILENAME = 'pool_mng_cert'
MGMT_PUBLIC_KEY_FILENAME = 'pool_mng_key.pub'
USER_PUBLIC_KEY_FILENAME = 'user_key.pub'


class AnsibleDockerRunner:
    """
    Represents Docker container environment for executing Ansible.
    """
    DOCKER_NETWORK = settings.KYPO_CONFIG.ansible_docker_network
    ANSIBLE_DOCKER_SSH_DIR = DockerVolume(
        bind='/root/.ssh',
        mode='rw'
    )
    ANSIBLE_DOCKER_INVENTORY_PATH = DockerVolume(
        bind='/app/inventory.yml',
        mode='ro'
    )

    def __init__(self, directory_path: str):
        self.client = docker.from_env()
        self.directory_path = directory_path
        self.ssh_directory = os.path.join(self.directory_path, 'ssh')
        self.inventory_path = os.path.join(self.directory_path, ANSIBLE_INVENTORY_FILENAME)

        self.container_mgmt_private_key = self.container_ssh_path(MGMT_PRIVATE_KEY_FILENAME)
        self.container_git_private_key =\
            self.container_ssh_path(settings.KYPO_CONFIG.git_private_key)
        self.container_proxy_private_key =\
            self.container_ssh_path(settings.KYPO_CONFIG.proxy_jump_to_man.IdentityFile)

    def run_container(self, url, rev, ansible_cleanup=False):
        """
        Run Ansible in Docker container.
        """
        volumes = {
            self.ssh_directory: self.ANSIBLE_DOCKER_SSH_DIR.__dict__,
            self.inventory_path: self.ANSIBLE_DOCKER_INVENTORY_PATH.__dict__
        }
        command = ['-u', url, '-r', rev, '-i', self.ANSIBLE_DOCKER_INVENTORY_PATH.bind,
                   '-a', settings.KYPO_CONFIG.answers_storage_api]
        command += ['-c'] if ansible_cleanup else []
        LOG.debug("Ansible container options", command=command)
        return self.client.containers.run(settings.KYPO_CONFIG.ansible_docker_image, detach=True,
                                          command=command, volumes=volumes,
                                          network=self.DOCKER_NETWORK)

    def get_container(self, container_id: str) -> Container:
        """
        Return Docker container with given container ID.
        """
        return self.client.containers.get(container_id)

    def delete_container(self, container_id: str, force=True) -> None:
        """
        Delete Docker container with given container ID.
        Parameter `force` is whether to kill the running one.
        """
        container = self.get_container(container_id)
        container.remove(force=force)

    def _prepare_ssh_dir(self):
        """
        Create SSH directory with private keys for communication with Git and KYPO Proxy.
        """
        self.make_dir(self.ssh_directory)
        shutil.copy(settings.KYPO_CONFIG.git_private_key, self.ssh_directory)
        shutil.copy(settings.KYPO_CONFIG.proxy_jump_to_man.IdentityFile, self.ssh_directory)

    @staticmethod
    def make_dir(dir_path: str) -> None:
        """
        Create directory with missing subdirectories or just make sure it exist.
        """
        os.makedirs(dir_path, exist_ok=True)

    @staticmethod
    def save_file(file_path: str, data: str) -> None:
        """
        Save data to the file.
        """
        with open(file_path, 'w') as file:
            file.write(data)

    def host_ssh_path(self, filename: str):
        """
        Compose absolute path to file in SSH directory volume.
        """
        return os.path.join(self.ssh_directory, os.path.basename(filename))

    def container_ssh_path(self, filename):
        """
        Compose absolute path to file in SSH directory in the container.
        """
        return os.path.join(self.ANSIBLE_DOCKER_SSH_DIR.bind, os.path.basename(filename))


class AllocationAnsibleDockerRunner(AnsibleDockerRunner):
    """
    Represents Docker container environment for executing Ansible during allocation stage.
    """
    # TODO review this and refactor so that the private keys are not copied around
    def prepare_ssh_dir(self, pool: Pool, sandbox: Sandbox):
        """
        Prepare files for SSH communication that will be bind to Docker container.
        """
        self._prepare_ssh_dir()
        self.save_file(self.host_ssh_path(USER_PUBLIC_KEY_FILENAME), sandbox.public_user_key)
        self.save_file(self.host_ssh_path(MGMT_PUBLIC_KEY_FILENAME), pool.public_management_key)
        self.save_file(self.host_ssh_path(MGMT_PRIVATE_KEY_FILENAME), pool.private_management_key)
        self.save_file(self.host_ssh_path(MGMT_CERTIFICATE_FILENAME), pool.management_certificate)

        ans_ssh_config = sandboxes.get_ansible_sshconfig(sandbox, self.container_mgmt_private_key,
                                                         self.container_git_private_key,
                                                         self.container_proxy_private_key)
        self.save_file(self.host_ssh_path('config'), str(ans_ssh_config))

    def prepare_inventory_file(self, sandbox: Sandbox):
        """
        Prepare and save Ansible inventory file that will be bind to Docker container.
        """
        inventory_object = self.create_inventory(sandbox)
        self.save_file(self.inventory_path, inventory_object.serialize())

    def create_inventory(self, sandbox):
        """
        Return Ansible inventory file.
        """
        mgmt_public_certificate = self.container_ssh_path(MGMT_CERTIFICATE_FILENAME)
        mgmt_public_key = self.container_ssh_path(MGMT_PUBLIC_KEY_FILENAME)
        user_public_key = self.container_ssh_path(USER_PUBLIC_KEY_FILENAME)
        top_ins = sandboxes.get_topology_instance(sandbox)
        sau = sandbox.allocation_unit
        sas = sau.allocation_request.stackallocationstage
        if not hasattr(sas, 'heatstack'):
            raise exceptions.ApiException(f'The SandboxAllocationUnit ID={sas.id} '
                                          'does not have any HeatStack instance.')
        heatstack = sas.heatstack
        extra_vars = {
            'kypo_global_sandbox_allocation_unit_id': sau.id,
            'kypo_global_openstack_stack_id': heatstack.stack_id,
            'kypo_global_pool_id': sau.pool.id,
            'kypo_global_head_ip': settings.KYPO_CONFIG.kypo_head_ip,
        }
        return Inventory(sau.pool.get_pool_prefix(), sau.get_stack_name(),
                         top_ins, self.container_mgmt_private_key, mgmt_public_certificate,
                         mgmt_public_key, user_public_key, extra_vars)


class CleanupAnsibleDockerRunner(AnsibleDockerRunner):
    """
    Represents Docker container environment for executing Ansible during allocation stage.
    """
    def prepare_inventory_file(self, allocation_unit: SandboxAllocationUnit):
        """
        Prepare and save Ansible inventory file that will be bind to Docker container.
        """
        inventory_object = BaseInventory(allocation_unit.pool.get_pool_prefix(),
                                         allocation_unit.get_stack_name())
        inventory_object.add_variables(
            kypo_global_sandbox_allocation_unit_id=allocation_unit.id,
            kypo_global_pool_id=allocation_unit.pool.id
        )

        self.save_file(self.inventory_path, inventory_object.serialize())

    def prepare_ssh_dir(self, pool: Pool):
        """
        Prepare files for SSH communication that will be bind to Docker container.
        """
        self._prepare_ssh_dir()
        self.save_file(self.host_ssh_path(MGMT_PRIVATE_KEY_FILENAME), pool.private_management_key)

        proxy_jump = settings.KYPO_CONFIG.proxy_jump_to_man
        ans_ssh_config = \
            sshconfig.KypoAnsibleCleanupSSHConfig(proxy_jump.Host, proxy_jump.User,
                                                  self.container_proxy_private_key,
                                                  settings.KYPO_CONFIG.git_server,
                                                  settings.KYPO_CONFIG.git_user,
                                                  self.container_git_private_key)
        self.save_file(self.host_ssh_path('config'), str(ans_ssh_config))
