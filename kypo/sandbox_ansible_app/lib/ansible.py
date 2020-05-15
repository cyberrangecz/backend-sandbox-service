import os
import shutil

import docker
import structlog

from django.conf import settings

from docker.models.containers import Container
from kypo.openstack_driver.topology_instance import TopologyInstance

from kypo.sandbox_definition_app.lib.definition_providers import GitProvider

from kypo.sandbox_ansible_app.models import AnsibleAllocationStage
from kypo.sandbox_common_lib import exceptions
from kypo.sandbox_common_lib.kypo_config import KypoConfiguration
from kypo.sandbox_instance_app.models import Sandbox, StageType
from kypo.sandbox_ansible_app.lib.inventory import Inventory
from kypo.sandbox_instance_app.lib import sandboxes

LOG = structlog.get_logger()


class DockerVolume:
    def __init__(self, bind: str, mode: str):
        self.bind = bind
        self.mode = mode


ANSIBLE_DOCKER_SSH_DIR = DockerVolume(
    bind='/root/.ssh',
    mode='rw'
)
ANSIBLE_DOCKER_INVENTORY_PATH = DockerVolume(
    bind='/app/inventory.yml',
    mode='ro'
)
ANSIBLE_DOCKER_LOCAL_REPO = DockerVolume(
    bind='path',
    mode='ro'
)

ANSIBLE_INVENTORY_FILENAME = 'inventory.yml'
MNG_PRIVATE_KEY_FILENAME = 'pool_mng_key'
USER_PRIVATE_KEY_FILENAME = 'user_key'
USER_PUBLIC_KEY_FILENAME = 'user_key.pub'


class AnsibleDockerRunner:
    DOCKER_NETWORK = settings.KYPO_CONFIG.ansible_docker_network

    def __init__(self):
        self.client = docker.from_env()

    def run_container(self, image, url, rev, ssh_dir, inventory_path):
        """Run Ansible in Docker container."""
        volumes = {
            ssh_dir: ANSIBLE_DOCKER_SSH_DIR.__dict__,
            inventory_path: ANSIBLE_DOCKER_INVENTORY_PATH.__dict__
        }
        if GitProvider.is_local_repo(url):
            local_path = GitProvider.get_local_repo_path(url)
            volumes[local_path] = ANSIBLE_DOCKER_LOCAL_REPO.__dict__
            volumes[local_path]['bind'] = local_path

        command = ['-u', url, '-r', rev, '-i', ANSIBLE_DOCKER_INVENTORY_PATH.bind]
        LOG.debug("Ansible container options", command=command)
        return self.client.containers.run(image, detach=True,
                                          command=command, volumes=volumes, network=self.DOCKER_NETWORK)

    def get_container(self, container_id: str) -> Container:
        return self.client.containers.get(container_id)

    def delete_container(self, container_id: str, force=True) -> None:
        """Delete given container. Parameter `force` is whether to kill the running one."""
        container = self.get_container(container_id)
        container.remove(force=force)

    # TODO review this and refactor so that the private keys are not copied around
    def prepare_ssh_dir(self, dir_path: str, stage: AnsibleAllocationStage, sandbox: Sandbox,
                        config: KypoConfiguration) -> str:
        """Prepare files that will be passed to docker container."""
        self.make_dir(dir_path)
        ssh_directory = os.path.join(dir_path, 'ssh')
        self.make_dir(ssh_directory)

        self.save_file(os.path.join(ssh_directory, USER_PRIVATE_KEY_FILENAME),
                       sandbox.private_user_key)
        self.save_file(os.path.join(ssh_directory, USER_PUBLIC_KEY_FILENAME),
                       sandbox.public_user_key)
        self.save_file(os.path.join(ssh_directory, MNG_PRIVATE_KEY_FILENAME),
                       stage.request.allocation_unit.pool.private_management_key)

        if not GitProvider.is_local_repo(stage.repo_url):
            shutil.copy(config.git_private_key,
                        os.path.join(ssh_directory, os.path.basename(config.git_private_key)))

        mng_key = os.path.join(ANSIBLE_DOCKER_SSH_DIR.bind, MNG_PRIVATE_KEY_FILENAME)
        git_key = os.path.join(ANSIBLE_DOCKER_SSH_DIR.bind,
                               os.path.basename(config.git_private_key))
        proxy_key = None
        if config.proxy_jump_to_man:
            proxy_key = os.path.join(ANSIBLE_DOCKER_SSH_DIR.bind,
                                     os.path.basename(config.proxy_jump_to_man.IdentityFile))
            shutil.copy(config.proxy_jump_to_man.IdentityFile, os.path.join(
                ssh_directory, os.path.basename(config.proxy_jump_to_man.IdentityFile)))

        ans_ssh_config = sandboxes.get_ansible_sshconfig(sandbox, mng_key, git_key, proxy_key)
        self.save_file(os.path.join(ssh_directory, 'config'), str(ans_ssh_config))

        return ssh_directory

    def prepare_inventory_file(self, dir_path: str, sandbox: Sandbox,
                               top_ins: TopologyInstance) -> str:
        """Prepare inventory file and save it to given directory."""
        user_private_key = os.path.join(ANSIBLE_DOCKER_SSH_DIR.bind,
                                        USER_PRIVATE_KEY_FILENAME)
        user_public_key = os.path.join(ANSIBLE_DOCKER_SSH_DIR.bind,
                                       USER_PUBLIC_KEY_FILENAME)
        os_stage = sandbox.allocation_unit.allocation_request.stages \
            .filter(type=StageType.OPENSTACK.value).select_subclasses().first()
        if not hasattr(os_stage, 'heatstack'):
            raise exceptions.ApiException(f'The openstack stage ID={os_stage.id} '
                                          'does not have any HeatStack intance.')
        heatstack = os_stage.heatstack

        inventory = Inventory(
            top_ins, user_private_key, user_public_key,
            {'kypo_global_sandbox_allocation_unit_id': sandbox.allocation_unit.id,
             'kypo_global_openstack_stack_id': heatstack.stack_id}
        )
        inventory_path = os.path.join(dir_path, ANSIBLE_INVENTORY_FILENAME)
        self.save_file(inventory_path, inventory.serialize())

        return inventory_path

    @staticmethod
    def make_dir(dir_path: str) -> None:
        os.makedirs(dir_path, exist_ok=True)

    @staticmethod
    def save_file(file_path: str, data: str) -> None:
        with open(file_path, 'w') as file:
            file.write(data)
