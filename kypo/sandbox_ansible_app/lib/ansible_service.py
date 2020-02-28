import re

import docker
import structlog

from kypo.sandbox_common_lib.utils import AttrDict

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


class AnsibleDockerContainer:
    def __init__(self, image, url, rev, ssh_dir, inventory_path):
        self.client = docker.from_env()
        self.killed = False

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
        self.container = self.client.containers.run(image, detach=True,
                                                    command=command, volumes=volumes)

    @property
    def id(self) -> str:
        return self.container.id

    def logs(self, **kwargs):
        return self.container.logs(**kwargs)

    def wait(self, **kwargs):
        return self.container.wait(**kwargs)

    @staticmethod
    def is_local_repo(url: str) -> bool:
        return url.startswith('file://')

    @staticmethod
    def local_repo_path(url: str) -> str:
        return re.sub('^file://', '', url)


def delete_docker_container(container_id: str) -> None:
    client = docker.from_env()
    container = client.get(container_id)
    container.remove(force=True)  # force: kill running container


def get_logs(container_id: str) -> str:
    client = docker.from_env()
    container = client.get(container_id)
    return container.logs
