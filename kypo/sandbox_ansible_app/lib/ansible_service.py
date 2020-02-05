import re

import docker
import structlog

from ...sandbox_common_lib.config import config

LOG = structlog.get_logger()


class AnsibleRunDockerContainer:
    def __init__(self, image, url, rev, ssh_dir, inventory_path):
        self.client = docker.from_env()
        self.killed = False

        volumes = {
            ssh_dir: config.ANSIBLE_DOCKER_VOLUMES_MAPPING['SSH_DIR'],
            inventory_path: config.ANSIBLE_DOCKER_VOLUMES_MAPPING['INVENTORY_PATH']
        }
        if self.is_local_repo(url):
            local_path = self.local_repo_path(url)
            volumes[local_path] = config.ANSIBLE_DOCKER_VOLUMES_MAPPING['LOCAL_REPO']
            volumes[local_path]['bind'] = local_path

        command = ['-u', url, '-r', rev, '-i',
                   config.ANSIBLE_DOCKER_VOLUMES_MAPPING['INVENTORY_PATH']['bind']]
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
    container.remove(force=True)  # kill running container


def get_logs(container_id: str) -> str:
    client = docker.from_env()
    container = client.get(container_id)
    return container.logs
