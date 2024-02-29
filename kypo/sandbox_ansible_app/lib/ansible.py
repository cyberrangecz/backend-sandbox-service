import os
import shutil
import docker  # used by unit tests

from jinja2 import Environment, FileSystemLoader
import structlog

from kypo.sandbox_common_lib.kypo_config import KypoConfiguration
from kypo.sandbox_service_project import settings
from kypo.cloud_commons import TopologyInstance

from kypo.sandbox_ansible_app.lib.container import KubernetesContainer, DockerContainer, \
    BaseContainer
from kypo.sandbox_ansible_app.lib.inventory import Inventory, BaseInventory
from kypo.sandbox_common_lib import exceptions
from kypo.sandbox_definition_app.lib import definitions
from kypo.sandbox_instance_app.lib import sandboxes, sshconfig
from kypo.sandbox_instance_app.models import Sandbox, Pool, SandboxAllocationUnit
from kypo.sandbox_common_lib.git_config import get_git_server

LOG = structlog.get_logger()


class DockerVolume:
    def __init__(self, name: str, bind: str, mode: str):
        self.name = name
        self.bind = bind
        self.mode = mode


ANSIBLE_INVENTORY_FILENAME = 'inventory.yml'
MGMT_PRIVATE_KEY_FILENAME = 'pool_mng_key'
MGMT_CERTIFICATE_FILENAME = 'pool_mng_cert'
MGMT_PUBLIC_KEY_FILENAME = 'pool_mng_key.pub'
USER_PUBLIC_KEY_FILENAME = 'user_key.pub'
ANSIBLE_DOCKER_CONTAINER_DIR = 'containers'
TEMPLATES_DIR_PATH = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'templates')
DOCKER_COMPOSE_TEMPLATE = 'docker-compose.j2'
DOCKERFILE_TEMPLATE = 'Dockerfile.j2'
GIT_CREDENTIALS_FILENAME = '.git-credentials'


class AnsibleRunner:
    """
    Represents Docker container environment for executing Ansible.
    """
    DOCKER_NETWORK = settings.KYPO_CONFIG.ansible_docker_network
    ANSIBLE_DOCKER_SSH_DIR = DockerVolume(
        name='ansible-ssh-dir',
        bind='/root/.ssh',
        mode='rw'
    )
    ANSIBLE_DOCKER_INVENTORY_PATH = DockerVolume(
        name='ansible-inventory-path',
        bind='/app/inventory.yml',
        mode='ro'
    )
    ANSIBLE_DOCKER_CONTAINER_PATH = DockerVolume(
        name='docker-containers-path',
        bind='/root/containers',
        mode='rw'
    )
    GIT_CREDENTIALS_PATH = DockerVolume(
        name='git-credentials-path',
        bind='/app/.git-credentials',
        mode='ro'
    )

    def __init__(self, directory_path: str):
        self.directory_path = directory_path
        self.ssh_directory = os.path.join(self.directory_path, 'ssh')
        self.inventory_path = os.path.join(self.directory_path, ANSIBLE_INVENTORY_FILENAME)
        self.containers_path = os.path.join(self.directory_path, ANSIBLE_DOCKER_CONTAINER_DIR)
        self.git_credentials = os.path.join(self.directory_path, GIT_CREDENTIALS_FILENAME)

        self.container_mgmt_private_key = self.container_ssh_path(MGMT_PRIVATE_KEY_FILENAME)
        self.container_proxy_private_key =\
            self.container_ssh_path(settings.KYPO_CONFIG.proxy_jump_to_man.IdentityFile)

        self.container_manager = KubernetesContainer\
            if settings.KYPO_CONFIG.ansible_runner_settings.backend == 'kubernetes'\
            else DockerContainer
        self.template_environment = Environment(loader=(FileSystemLoader(TEMPLATES_DIR_PATH)))

    def run_ansible_playbook(self, url, rev, stage, cleanup=False) -> BaseContainer:
        """
        Run Ansible playbook in container.
        """
        return self.container_manager(url, rev, stage, self.ssh_directory,
                                      self.inventory_path, self.containers_path,
                                      self.git_credentials, cleanup)

    def delete_container(self, container_name: str) -> None:
        """
        Delete container with given container name.
        """
        self.container_manager.delete_container(container_name)

    def _prepare_ssh_dir(self):
        """
        Create SSH directory with private key for communication with KYPO Proxy.
        """
        self.make_dir(self.ssh_directory)
        shutil.copy(settings.KYPO_CONFIG.proxy_jump_to_man.IdentityFile, self.ssh_directory)

    def _prepare_container_directory(self):
        self.make_dir(self.containers_path)

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

    def prepare_git_credentials(self, config: KypoConfiguration):
        # TODO refactor with multiple gitlab feature
        username = config.git_user
        credentials = ""
        for host, token in config.git_providers.items():
            credentials += f'https://{username}:{token}@{get_git_server(host)}\n'
        return self.save_file(self.git_credentials, credentials)


class AllocationAnsibleRunner(AnsibleRunner):
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
                                                         self.container_proxy_private_key)
        self.save_file(self.host_ssh_path('config'), str(ans_ssh_config))


    def prepare_inventory_file(self, sandbox: Sandbox):
        """
        Prepare and save Ansible inventory file that will be bind to Docker container.
        """
        inventory_object = self.create_inventory(sandbox)
        self.save_file(self.inventory_path, inventory_object.serialize())

    def _generate_docker_composes(self, top_ins: TopologyInstance):
        parsed_docker_hosts = []
        for container_mapping in top_ins.containers.container_mappings:
            if container_mapping.host not in parsed_docker_hosts:
                containers_host_path = os.path.join(self.containers_path, container_mapping.host)
                self.make_dir(containers_host_path)
                current_container_mappings = [mapping for mapping
                                              in top_ins.containers.container_mappings
                                              if mapping.host == container_mapping.host]
                try:
                    template = self.template_environment.get_template(DOCKER_COMPOSE_TEMPLATE)
                    docker_compose = template.render(container_mappings=current_container_mappings,
                                                     containers=top_ins.containers.containers)
                    docker_compose_path = os.path.join(containers_host_path, 'docker-compose.yml')
                    self.save_file(docker_compose_path, docker_compose)
                except Exception as e:
                    raise exceptions.ApiException("Error while generating docker-compose "
                                                  "template: ", e)
                parsed_docker_hosts.append(container_mapping.host)

    def _generate_dockerfiles(self, sandbox: Sandbox):
        top_ins = sandboxes.get_topology_instance(sandbox)
        for container_mapping in top_ins.containers.container_mappings:
            host_path = os.path.join(self.containers_path, container_mapping.host)
            host_container_path = os.path.join(host_path, container_mapping.container)
            self.make_dir(host_container_path)
            container_definition = [cont for cont in top_ins.containers.containers
                                    if cont.name == container_mapping.container][0]
            if container_definition.image:
                try:
                    template = self.template_environment.get_template(DOCKERFILE_TEMPLATE)
                    dockerfile = template.render(container_definition=container_definition)
                except Exception as e:
                    raise exceptions.ApiException(
                        "Error while generating dockerfile from template: ", e)
            else:
                dockerfile_path = container_definition.dockerfile
                url = sandbox.allocation_unit.pool.definition.url
                rev = sandbox.allocation_unit.pool.definition.rev
                dockerfile = definitions.get_dockerfile(url, rev, settings.KYPO_CONFIG,
                                                        dockerfile_path)
            self.save_file(os.path.join(host_container_path, "Dockerfile"), dockerfile)

    def prepare_containers_directory(self, sandbox: Sandbox):
        top_ins = sandboxes.get_topology_instance(sandbox)
        if top_ins.containers:
            self._prepare_container_directory()
            self._generate_docker_composes(top_ins)
            self._generate_dockerfiles(sandbox)

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
        if not hasattr(sas, 'terraformstack'):
            raise exceptions.ApiException(f'The SandboxAllocationUnit ID={sas.id} '
                                          'does not have any TerraformStack instance.')
        terraformstack = sas.terraformstack
        extra_vars = {
            'kypo_global_sandbox_allocation_unit_id': sau.id,
            'kypo_global_sandbox_id': sau.sandbox.id,
            'kypo_global_openstack_stack_id': terraformstack.stack_id,
            'kypo_global_pool_id': sau.pool.id,
            'kypo_global_head_ip': settings.KYPO_CONFIG.kypo_head_ip,
        }
        return Inventory(sau.pool.get_pool_prefix(), sau.get_stack_name(),
                         top_ins, self.container_mgmt_private_key, mgmt_public_certificate,
                         mgmt_public_key, user_public_key, extra_vars)


class CleanupAnsibleRunner(AnsibleRunner):
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
                                                  self.container_proxy_private_key)
        self.save_file(self.host_ssh_path('config'), str(ans_ssh_config))
