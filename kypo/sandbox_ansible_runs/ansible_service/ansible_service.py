import docker

import structlog

from ...sandbox_common.config import config

LOG = structlog.get_logger()


class AnsibleRunDockerContainer:
    def __init__(self, image, url, rev, ssh_dir, inventory_path):
        self.client = docker.from_env()
        self.killed = False

        command = ['-u', url, '-r', rev, '-i',
                   config.ANSIBLE_DOCKER_VOLUMES_MAPPING['INVENTORY_PATH']['bind']]
        volumes = {
            ssh_dir: config.ANSIBLE_DOCKER_VOLUMES_MAPPING['SSH_DIR'],
            inventory_path: config.ANSIBLE_DOCKER_VOLUMES_MAPPING['INVENTORY_PATH']
        }
        self.container = self.client.containers.run(image, detach=True,
                                                    command=command, volumes=volumes)

    @property
    def id(self) -> str:
        return self.container.id

    def logs(self, **kwargs):
        return self.container.logs(**kwargs)

    def wait(self, **kwargs):
        return self.container.wait(**kwargs)


def delete_docker_container(container_id: str) -> None:
    client = docker.from_env()
    container = client.get(container_id)
    container.remove(force=True)  # kill running container
