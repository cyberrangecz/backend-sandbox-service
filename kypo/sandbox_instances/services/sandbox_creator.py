import io
from typing import List
import django_rq
import structlog
from django.utils import timezone
import yaml
import os
import shutil
import docker.errors
import requests.exceptions as requests_exceptions

from kypo2_openstack_lib.stack import Event, Resource
from . import utils, ansible_service, definition_service, sandbox_service
from ..config import config
from .. import exceptions
from ..models import Sandbox, Pool, SandboxCreateRequest, StackCreateStage, AnsibleStage, AnsibleOutput

STACK_STATUS_CREATE_COMPLETE = "CREATE_COMPLETE"

LOG = structlog.get_logger()


def create_sandbox_requests(pool: Pool, count: int) -> List[SandboxCreateRequest]:
    """
    Creates Sandbox Requests.
    Also creates sandboxes, but does not save them to the database until successfully created.
    """
    requests = []
    sandboxes = []
    for _ in range(count):
        request = SandboxCreateRequest.objects.create(pool=pool)
        requests.append(request)

        pri_key, pub_key = utils.generate_ssh_keypair()
        sandbox = Sandbox(id=request.id, request=request, private_user_key=pri_key,
                          public_user_key=pub_key)
        sandboxes.append(sandbox)
    enqueue_requests(requests, sandboxes)
    return requests


def enqueue_requests(requests: List[SandboxCreateRequest], sandboxes) -> None:
    for request, sandbox in zip(requests, sandboxes):

        stage_openstack = StackCreateStage.objects.create(request=request)
        queue_openstack = django_rq.get_queue(config.OPENSTACK_QUEUE, default_timeout=config.SANDBOX_BUILD_TIMEOUT)
        result_openstack = queue_openstack.enqueue(StackCreateStageManager().run,
                                                   stage=stage_openstack, sandbox=sandbox)

        stage_networking = AnsibleStage.objects.create(request=request,
                                                       repo_url=config.ANSIBLE_NETWORKING_URL,
                                                       rev=config.ANSIBLE_NETWORKING_REV)
        queue_ansible = django_rq.get_queue(config.ANSIBLE_QUEUE, default_timeout=config.SANDBOX_ANSIBLE_TIMEOUT)
        result_networking = queue_ansible.enqueue(AnsibleStageManager(stage=stage_networking, sandbox=sandbox).run,
                                                  name='networking', depends_on=result_openstack)

        stage_user_ansible = AnsibleStage.objects.create(request=request,
                                                         repo_url=request.pool.definition.url,
                                                         rev=request.pool.definition.rev)
        result_user_ansible = queue_ansible.enqueue(AnsibleStageManager(stage=stage_user_ansible, sandbox=sandbox).run,
                                                    name='user-ansible', depends_on=result_networking)

        queue_default = django_rq.get_queue()
        queue_default.enqueue(save_sandbox_to_database, sandbox=sandbox, depends_on=result_user_ansible)


class StackCreateStageManager:
    def __init__(self):
        self._client = None

    @property
    def client(self):
        if not self._client:
            self._client = utils.get_ostack_client()
        return self._client

    def run(self, stage: StackCreateStage, sandbox: Sandbox) -> None:
        """Run the stage."""
        try:
            LOG.info("Stage 1 (StackCreationStage) started", stage=stage)
            stage.start = timezone.now()
            stage.save()
            self.build_sandbox(stage, sandbox)
            self.wait_for_stack_creation(stage)
        except Exception as ex:
            stage.mark_failed(ex)
            raise
        finally:
            stage.end = timezone.now()
            stage.save()

    def build_sandbox(self, stage: StackCreateStage, sandbox: Sandbox) -> None:
        """Build sandbox in OpenStack."""
        LOG.debug("Building sandbox", sandbox=stage)
        definition = definition_service.get_sandbox_definition(
            url=sandbox.request.pool.definition.url,
            rev=sandbox.request.pool.definition.rev
        )
        self.client.create_sandbox(io.StringIO(definition), sandbox.get_stack_name(),
                                   SSH_KEY_NAME=stage.request.pool.get_keypair_name(),
                                   **config.SANDBOX_CONFIGURATION)

    def wait_for_stack_creation(self, stage: StackCreateStage) -> None:
        """Wait for stack creation."""
        def sandbox_create_check():
            stacks = self.client.list_sandboxes()
            stack = stacks[stage.request.get_stack_name()]
            if self.is_status_failed(stack.stack_status):
                raise exceptions.InterruptError("sandbox creation failed")
            return stack.stack_status == STACK_STATUS_CREATE_COMPLETE

        utils.wait_for(sandbox_create_check, config.SANDBOX_BUILD_TIMEOUT, freq=10, initial_wait=3,
                       errmsg="Sandbox build exceeded timeout of {} sec. Stage: {}"
                       .format(config.SANDBOX_BUILD_TIMEOUT, str(stage)))

        LOG.info("Sandbox created successfully", stage=stage)

    @staticmethod
    def is_status_failed(status: str) -> bool:
        """Check whether the status indicates, that stack create failed."""
        return status == "ROLLBACK_COMPLETE" or status == "ROLLBACK_FAILED"

    def update_stage(self, stage: StackCreateStage) -> StackCreateStage:
        """Update stage with current stack status from OpenStack."""
        sandboxes = self.client.list_sandboxes()
        sb = sandboxes[stage.request.get_stack_name()]
        stage.status = sb.stack_status
        stage.status_reason = sb.stack_status_reason
        stage.save()
        return stage

    def get_events(self, stage: StackCreateStage) -> List[Event]:
        """List all events in sandbox as Events objects."""
        return self.client.list_sandbox_events(stage.request.get_stack_name())

    def get_resources(self, stage: StackCreateStage) -> List[Resource]:
        """List all resources in sandbox as Resource objects."""
        return self.client.list_sandbox_resources(stage.request.get_stack_name())


class AnsibleStageManager:
    def __init__(self, stage: AnsibleStage, sandbox: Sandbox) -> None:
        self.stage = stage
        self.sandbox = sandbox
        self.directory = os.path.join(config.ANSIBLE_DOCKER_VOLUMES,
                                      sandbox.get_stack_name(), str(stage.id))
        self.make_dir(self.directory)

    def run(self, name: str) -> None:
        """Run the stage."""
        try:
            LOG.info("Stage {} (AnsibleRunStage) started".format(name), stage=self.stage)
            self.stage.start = timezone.now()
            self.stage.save()
            self.run_docker_container()
        except Exception as ex:
            self.stage.mark_failed(ex)
            raise
        finally:
            self.stage.end = timezone.now()
            self.stage.save()

    @staticmethod
    def make_dir(dir_path: str) -> None:
        try:
            os.makedirs(dir_path, exist_ok=True)
        except FileExistsError as e:
            raise exceptions.ApiException(e)

    @staticmethod
    def save_file(file_path: str, data: str) -> None:
        with open(file_path, 'w') as file:
            file.write(data)

    def prepare_ssh_dir(self) -> str:
        """
        Prepare files that will be passed to docker container.

        :return: None
        """

        ssh_directory = os.path.join(self.directory, 'ssh')
        self.make_dir(ssh_directory)

        self.save_file(os.path.join(ssh_directory, config.USER_PRIVATE_KEY_FILENAME), self.sandbox.private_user_key)
        self.save_file(os.path.join(ssh_directory, config.USER_PUBLIC_KEY_FILENAME), self.sandbox.public_user_key)
        self.save_file(os.path.join(ssh_directory, config.MNG_PRIVATE_KEY_FILENAME),
                       self.stage.request.pool.private_management_key)

        shutil.copy(config.GIT_PRIVATE_KEY, os.path.join(ssh_directory, os.path.basename(config.GIT_PRIVATE_KEY)))

        stack = utils.get_ostack_client().get_sandbox(self.sandbox.get_stack_name())
        mng_private_key = os.path.join(config.ANSIBLE_DOCKER_VOLUMES_MAPPING['SSH_DIR']['bind'],
                                       config.MNG_PRIVATE_KEY_FILENAME)
        git_private_key = os.path.join(config.ANSIBLE_DOCKER_VOLUMES_MAPPING['SSH_DIR']['bind'],
                                       os.path.basename(config.GIT_PRIVATE_KEY))
        management_ssh_config = sandbox_service.SandboxSSHConfigCreator(self.sandbox).create_management_config()
        for pattern in management_ssh_config.get_hosts():
            management_ssh_config.update_entry(pattern, UserKnownHostsFile='/dev/null', StrictHostKeyChecking='no',
                                               IdentityFile=mng_private_key)
        management_ssh_config.add_entry(Host=config.GIT_SERVER, User=config.GIT_USER, IdentityFile=git_private_key,
                                        UserKnownHostsFile='/dev/null', StrictHostKeyChecking='no')
        if config.PROXY_JUMP_TO_MAN_SSH_OPTIONS:
            shutil.copy(config.PROXY_JUMP_TO_MAN_PRIVATE_KEY,
                        os.path.join(ssh_directory, os.path.basename(config.PROXY_JUMP_TO_MAN_PRIVATE_KEY)))
            proxy_jump_to_man_private_key = os.path.join(config.ANSIBLE_DOCKER_VOLUMES_MAPPING['SSH_DIR']['bind'],
                                                         os.path.basename(config.PROXY_JUMP_TO_MAN_PRIVATE_KEY))
            management_ssh_config.add_entry(**config.PROXY_JUMP_TO_MAN_SSH_OPTIONS)
            management_ssh_config.update_entry(config.PROXY_JUMP_TO_MAN_SSH_OPTIONS['Host'],
                                               IdentityFile=proxy_jump_to_man_private_key,
                                               UserKnownHostsFile='/dev/null', StrictHostKeyChecking='no')
            management_ssh_config.update_entry(stack.man.name,
                                               ProxyJump=config.PROXY_JUMP_TO_MAN_SSH_OPTIONS['Host'])
        self.save_file(os.path.join(ssh_directory, 'config'), str(management_ssh_config))

        return ssh_directory

    def prepare_inventory_file(self) -> str:
        definition = self.stage.request.pool.definition
        sandbox_definition = yaml.full_load(definition_service.get_sandbox_definition(definition.url, definition.rev))

        client = utils.get_ostack_client()
        stack = client.get_sandbox(self.sandbox.get_stack_name())
        user_private_key = os.path.join(config.ANSIBLE_DOCKER_VOLUMES_MAPPING['SSH_DIR']['bind'],
                                        config.USER_PRIVATE_KEY_FILENAME)
        user_public_key = os.path.join(config.ANSIBLE_DOCKER_VOLUMES_MAPPING['SSH_DIR']['bind'],
                                       config.USER_PUBLIC_KEY_FILENAME)
        inventory = ansible_service.Inventory.create_inventory(stack, sandbox_definition,
                                                               user_private_key, user_public_key)

        inventory_path = os.path.join(self.directory, config.ANSIBLE_INVENTORY_FILENAME)
        self.save_file(inventory_path, yaml.dump(inventory, default_flow_style=False, indent=2))

        return inventory_path

    def run_docker_container(self) -> None:
        ssh_directory = self.prepare_ssh_dir()
        inventory_path = self.prepare_inventory_file()

        try:
            container = ansible_service.AnsibleRunDockerContainer(config.ANSIBLE_DOCKER_IMAGE, self.stage.repo_url,
                                                                  self.stage.rev, ssh_directory, inventory_path)
            for output in container.logs(stream=True):
                output = output.decode('utf-8')
                output = output[:-1] if output[-1] == '\n' else output
                AnsibleOutput.objects.create(ansible_run=self.stage, content=output)

            status = container.wait(timeout=60)
        except (docker.errors.APIError,
                docker.errors.DockerException,
                requests_exceptions.ReadTimeout) as ex:
            raise exceptions.DockerError(ex)

        status_code = status['StatusCode']
        if status_code != 0:
            raise exceptions.AnsibleError('Ansible ID={} failed with status code \'{}\''
                                          .format(self.stage.id, status_code))


def save_sandbox_to_database(sandbox):
    sandbox.save()
