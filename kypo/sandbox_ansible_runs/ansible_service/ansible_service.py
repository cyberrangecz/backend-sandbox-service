from typing import Generator
import docker

import structlog

from ...common.config import config
from ..models import AnsibleAllocationStage

LOG = structlog.get_logger()


class AnsibleRunDockerContainer:
    container = None
    killed = False

    def __init__(self, image, url, rev, ssh_dir, inventory_path):
        self.client = docker.from_env()
        command = ['-u', url, '-r', rev, '-i',
                   config.ANSIBLE_DOCKER_VOLUMES_MAPPING['INVENTORY_PATH']['bind']]
        volumes = {
            ssh_dir: config.ANSIBLE_DOCKER_VOLUMES_MAPPING['SSH_DIR'],
            inventory_path: config.ANSIBLE_DOCKER_VOLUMES_MAPPING['INVENTORY_PATH']
        }
        self.container = self.client.containers.run(image, detach=True,
                                                    command=command, volumes=volumes)

    @property
    def id(self):
        return self.container.id

    def logs(self, **kwargs):
        return self.container.logs(**kwargs)

    def wait(self, **kwargs):
        return self.container.wait(**kwargs)
