import os
import re
import shutil

import docker
import structlog
from docker.models.containers import Container
from kypo.topology_definition.models import TopologyDefinition

from kypo.sandbox_common_lib.utils import AttrDict
from kypo.sandbox_ansible_app.models import AnsibleAllocationStage
from kypo.sandbox_common_lib import utils
from kypo.sandbox_common_lib.config import KypoConfiguration
from kypo.sandbox_instance_app.models import Sandbox
from kypo.sandbox_ansible_app.lib.inventory import Inventory
from kypo.sandbox_instance_app.lib import sandbox_service

LOG = structlog.get_logger()

ANSIBLE_DOCKER_SSH_DIR = AttrDict(
    bind='/root/.ssh',
    mode='rw'
)
ANSIBLE_DOCKER_INVENTORY_PATH = AttrDict(
    bind='/app/inventory.yml',
    mode='ro'
)
ANSIBLE_DOCKER_LOCAL_REPO = AttrDict(
    bind='path',
    mode='ro'
)

ANSIBLE_INVENTORY_FILENAME = 'inventory.yml'
MNG_PRIVATE_KEY_FILENAME = 'pool_mng_key'
USER_PRIVATE_KEY_FILENAME = 'user_key'
USER_PUBLIC_KEY_FILENAME = 'user_key.pub'


class AnsibleDockerRunner:

    def __init__(self):
        self.client = docker.from_env()

    def run_container(self, image, url, rev, ssh_dir, inventory_path):
        """Run Ansible in Docker container."""
        volumes = {
            ssh_dir: ANSIBLE_DOCKER_SSH_DIR,
            inventory_path: ANSIBLE_DOCKER_INVENTORY_PATH
        }
        if self.is_local_repo(url):
            local_path = self.local_repo_path(url)
            volumes[local_path] = ANSIBLE_DOCKER_LOCAL_REPO
            volumes[local_path]['bind'] = local_path

        command = ['-u', url, '-r', rev, '-i', ANSIBLE_DOCKER_INVENTORY_PATH.bind]
        LOG.debug("Ansible container options", command=command)
        return self.client.containers.run(image, detach=True,
                                          command=command, volumes=volumes)

    def get_container(self, container_id: str) -> Container:
        return self.client.get(container_id)

    def delete_container(self, container_id: str, force=True) -> None:
        """Delete given container. Parameter `force` is whether to kill the running one."""
        container = self.get_container(container_id)
        container.remove(force=force)

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

        if not AnsibleDockerRunner.is_local_repo(stage.repo_url):
            shutil.copy(config.git_private_key,
                        os.path.join(ssh_directory, os.path.basename(config.git_private_key)))

        mng_key = os.path.join(ANSIBLE_DOCKER_SSH_DIR.bind, MNG_PRIVATE_KEY_FILENAME)
        git_key = os.path.join(ANSIBLE_DOCKER_SSH_DIR.bind,
                               os.path.basename(config.git_private_key))
        proxy_key = None
        if config.proxy_jump_to_man:
            proxy_key = os.path.join(ANSIBLE_DOCKER_SSH_DIR.bind,
                                     os.path.basename(config.proxy_jump_to_man.IdentityFile))
        ans_ssh_config = sandbox_service.get_ansible_sshconfig(sandbox, mng_key, git_key, proxy_key)

        identity_file = config.proxy_jump_to_man.IdentityFile
        shutil.copy(identity_file, os.path.join(ssh_directory,
                                                os.path.basename(identity_file)))
        self.save_file(os.path.join(ssh_directory, 'config'), str(ans_ssh_config))

        return ssh_directory

    def prepare_inventory_file(self, dir_path: str, stack_name: str,
                               top_def: TopologyDefinition) -> str:
        """Prepare inventory file and save it to given directory."""
        client = utils.get_ostack_client()
        stack = client.get_sandbox(stack_name)
        user_private_key = os.path.join(ANSIBLE_DOCKER_SSH_DIR.bind,
                                        USER_PRIVATE_KEY_FILENAME)
        user_public_key = os.path.join(ANSIBLE_DOCKER_SSH_DIR.bind,
                                       USER_PUBLIC_KEY_FILENAME)
        inventory = Inventory(stack, top_def, user_private_key, user_public_key)

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

    @staticmethod
    def is_local_repo(url: str) -> bool:
        return url.startswith('file://')

    @staticmethod
    def local_repo_path(url: str) -> str:
        return re.sub('^file://', '', url)
