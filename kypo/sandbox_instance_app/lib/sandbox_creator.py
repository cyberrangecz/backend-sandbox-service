import os
import shutil
import time
from functools import partial
from typing import List, Callable

import django_rq
import docker.errors
import requests.exceptions as requests_exceptions
import rq
import structlog
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.utils import timezone
from kypo.openstack_driver.stack import Event, Resource
from rq.job import Job
from django.conf import settings

from kypo.sandbox_instance_app.lib import sandbox_service
from kypo.sandbox_instance_app.models import Sandbox, Pool, SandboxAllocationUnit, \
    AllocationRequest, StackAllocationStage, StackCleanupStage, Stage, HeatStack
from kypo.sandbox_ansible_app.lib import ansible_service
from kypo.sandbox_ansible_app.lib.ansible_service import ANSIBLE_DOCKER_SSH_DIR
from kypo.sandbox_ansible_app.lib.inventory import Inventory
from kypo.sandbox_ansible_app.models import AnsibleAllocationStage, AnsibleOutput, DockerContainer
from kypo.sandbox_common_lib import utils, exceptions
from kypo.sandbox_definition_app.lib import definition_service

STACK_STATUS_CREATE_COMPLETE = "CREATE_COMPLETE"

LOG = structlog.get_logger()

ANSIBLE_INVENTORY_FILENAME = 'inventory.yml'
MNG_PRIVATE_KEY_FILENAME = 'pool_mng_key'
USER_PRIVATE_KEY_FILENAME = 'user_key'
USER_PUBLIC_KEY_FILENAME = 'user_key.pub'
OPENSTACK_QUEUE = 'openstack'
ANSIBLE_QUEUE = 'ansible'


def create_sandbox_requests(pool: Pool, count: int) -> List[SandboxAllocationUnit]:
    """
    Creates Sandbox Requests.
    Also creates sandboxes, but does not save them to the database until
    successfully created.
    """
    units = []
    requests = []
    sandboxes = []
    for _ in range(count):
        unit = SandboxAllocationUnit.objects.create(pool=pool)
        request = AllocationRequest.objects.create(allocation_unit=unit)
        units.append(unit)
        requests.append(request)

        pri_key, pub_key = utils.generate_ssh_keypair()
        sandbox = Sandbox(id=request.id, allocation_unit=unit,
                          private_user_key=pri_key, public_user_key=pub_key)
        sandboxes.append(sandbox)
    enqueue_requests(requests, sandboxes)
    return units


def enqueue_requests(requests: List[AllocationRequest], sandboxes) -> None:
    for request, sandbox in zip(requests, sandboxes):
        with transaction.atomic():
            stage_openstack = StackAllocationStage.objects.create(request=request)
            queue_openstack = django_rq.get_queue(
                OPENSTACK_QUEUE, default_timeout=settings.KYPO_CONFIG.sandbox_build_timeout)
            result_openstack = queue_openstack.enqueue(
                StackStageHandler().build, stage=stage_openstack,
                sandbox=sandbox, meta=dict(locked=True))

            stage_networking = AnsibleAllocationStage.objects.create(
                request=request, repo_url=settings.KYPO_CONFIG.ansible_networking_url,
                rev=settings.KYPO_CONFIG.ansible_networking_rev
            )
            queue_ansible = django_rq.get_queue(
                ANSIBLE_QUEUE, default_timeout=settings.KYPO_CONFIG.sandbox_ansible_timeout)
            result_networking = queue_ansible.enqueue(
                AnsibleStageHandler(stage=stage_networking, sandbox=sandbox).build,
                name='networking', depends_on=result_openstack
            )

            stage_user_ansible = AnsibleAllocationStage.objects.create(
                request=request, repo_url=request.allocation_unit.pool.definition.url,
                rev=request.allocation_unit.pool.definition.rev
            )
            result_user_ansible = queue_ansible.enqueue(
                AnsibleStageHandler(stage=stage_user_ansible, sandbox=sandbox).build,
                name='user-ansible', depends_on=result_networking)

            queue_default = django_rq.get_queue()
            queue_default.enqueue(save_sandbox_to_database, sandbox=sandbox,
                                  depends_on=result_user_ansible)
            transaction.on_commit(partial(unlock_job, result_openstack))


def lock_job(timeout=60, step=5):
    job = rq.get_current_job()
    stage = job.kwargs.get('stage')
    elapsed = 0

    while elapsed <= timeout:
        job.refresh()
        locked = job.meta.get('locked', True)
        if not locked:
            LOG.debug('Stage unlocked.', stage=stage)
            break
        else:
            LOG.debug('Wait until the stage is unlocked.', stage=stage)
            time.sleep(step)
            elapsed += step


def unlock_job(job: Job):
    stage = job.kwargs.get('stage')
    if job.meta.get('locked', True):
        LOG.debug('Unlocking stage.', stage=stage)
    job.meta['locked'] = False
    job.save_meta()


class StageHandler:
    def run_stage(self, func: Callable, stage: Stage, *args, **kwargs) -> None:
        """Run the stage."""
        try:
            stage.start = timezone.now()
            stage.save()
            LOG.info(f'Stage {str(stage)} started', stage=stage)
            func(stage, *args, **kwargs)
        except Exception as ex:
            stage.mark_failed(ex)
            raise
        finally:
            stage.end = timezone.now()
            stage.save()


class StackStageHandler(StageHandler):
    def __init__(self):
        self._client = None

    @property
    def client(self):
        if not self._client:
            self._client = utils.get_ostack_client()
        return self._client

    def build(self, stage: StackAllocationStage, sandbox: Sandbox) -> None:
        """Run the stage."""
        try:
            lock_job()
        except Exception as ex:
            stage.mark_failed(ex)
            stage.end = timezone.now()
            stage.save()
            raise

        self.run_stage(self.build_stack, stage, sandbox)

    def cleanup(self, stage: StackCleanupStage) -> None:
        self.run_stage(self.delete_sandbox, stage)

    def build_stack(self, stage: StackAllocationStage, sandbox: Sandbox) -> None:
        """Build sandbox in OpenStack."""
        definition = sandbox.allocation_unit.pool.definition
        top_def = definition_service.get_definition(
                definition.url, definition.rev,
                'rev-{0}_stage-{1}'.format(definition.rev, stage.id)
        )
        stack = self.client.create_sandbox(
            sandbox.allocation_unit.get_stack_name(), top_def,
            kp_name=stage.request.allocation_unit.pool.get_keypair_name())

        HeatStack.objects.create(stage=stage, stack_id=stack['stack']['id'])

        self.wait_for_stack_creation(stage)

    def wait_for_stack_creation(self, stage: StackAllocationStage) -> None:
        name = stage.request.allocation_unit.get_stack_name()
        """Wait for stack creation."""
        success, msg = self.client.wait_for_stack_create_action(name)
        if not success:
            roll_succ, roll_msg = self.client.wait_for_stack_rollback_action(name)
            if not roll_succ:
                LOG.warning('Rollback failed', msg=roll_msg)
            raise exceptions.StackError(f'Sandbox build failed: {msg}')

        LOG.info("Stack created successfully", stage=stage)

    def delete_sandbox(self, stage: StackCleanupStage) -> None:
        """Deletes given sandbox. Hard specifies whether to use hard delete.
        On soft delete raises ValidationError if any sandbox is locked."""
        allocation_unit = stage.request.allocation_unit
        stack_name = allocation_unit.get_stack_name()

        try:
            sandbox = allocation_unit.sandbox
        except ObjectDoesNotExist:
            pass
        else:
            sandbox.delete()

        LOG.info('Starting Stack delete in OpenStack',
                 stack_name=stack_name, allocation_unit=allocation_unit)

        self.client.delete_sandbox(stack_name)
        self.wait_for_stack_deletion(stack_name)

        LOG.info('Stack deleted successfully from OpenStack',
                 stack_name=stack_name, allocation_unit=allocation_unit)

    def wait_for_stack_deletion(self, stack_name: str) -> None:
        """Wait for stack deletion."""
        success, msg = self.client.wait_for_stack_delete_action(stack_name)
        if not success:
            raise exceptions.StackError(f'Stack {stack_name} delete failed: {msg}')

    def update_stage(self, stage: StackAllocationStage) -> StackAllocationStage:
        """Update stage with current stack status from OpenStack."""
        sandboxes = self.client.list_sandboxes()
        sb = sandboxes[stage.request.allocation_unit.get_stack_name()]
        stage.status = sb.stack_status
        stage.status_reason = sb.stack_status_reason
        stage.save()
        return stage


class AnsibleStageHandler(StageHandler):
    def __init__(self, stage: AnsibleAllocationStage, sandbox: Sandbox) -> None:
        self.stage = stage
        self.sandbox = sandbox
        self.directory = os.path.join(settings.KYPO_CONFIG.ansible_docker_volumes,
                                      sandbox.allocation_unit.get_stack_name(),
                                      f'{stage.id}-{utils.get_simple_uuid()}')

    def build(self, name: str) -> None:
        """Run the stage."""
        self.run_stage(self.run_docker_container, self.stage)

    @staticmethod
    def make_dir(dir_path: str) -> None:
        os.makedirs(dir_path, exist_ok=True)

    @staticmethod
    def save_file(file_path: str, data: str) -> None:
        with open(file_path, 'w') as file:
            file.write(data)

    def prepare_ssh_dir(self) -> str:
        """Prepare files that will be passed to docker container."""
        config = settings.KYPO_CONFIG
        self.make_dir(self.directory)
        ssh_directory = os.path.join(self.directory, 'ssh')
        self.make_dir(ssh_directory)

        self.save_file(os.path.join(ssh_directory, USER_PRIVATE_KEY_FILENAME),
                       self.sandbox.private_user_key)
        self.save_file(os.path.join(ssh_directory, USER_PUBLIC_KEY_FILENAME),
                       self.sandbox.public_user_key)
        self.save_file(os.path.join(ssh_directory, MNG_PRIVATE_KEY_FILENAME),
                       self.stage.request.allocation_unit.pool.private_management_key)

        if not ansible_service.AnsibleRunDockerContainer.is_local_repo(self.stage.repo_url):
            shutil.copy(config.git_private_key,
                        os.path.join(ssh_directory, os.path.basename(config.git_private_key)))

        mng_key = os.path.join(ANSIBLE_DOCKER_SSH_DIR.bind, MNG_PRIVATE_KEY_FILENAME)
        git_key = os.path.join(ANSIBLE_DOCKER_SSH_DIR.bind,
                               os.path.basename(config.git_private_key))
        proxy_key = None
        if config.proxy_jump_to_man:
            proxy_key = os.path.join(ANSIBLE_DOCKER_SSH_DIR.bind,
                                     os.path.basename(config.proxy_jump_to_man.IdentityFile))
        ans_ssh_config = sandbox_service.get_ansible_sshconfig(self.sandbox, mng_key, git_key, proxy_key)

        identity_file = config.proxy_jump_to_man.IdentityFile
        shutil.copy(identity_file, os.path.join(ssh_directory,
                    os.path.basename(identity_file)))
        self.save_file(os.path.join(ssh_directory, 'config'), str(ans_ssh_config))

        return ssh_directory

    def prepare_inventory_file(self) -> str:
        definition = self.stage.request.allocation_unit.pool.definition
        top_def = definition_service.get_definition(
            definition.url, definition.rev,
            'rev-{0}_stage-{1}'.format(definition.rev, self.stage.id))

        client = utils.get_ostack_client()
        stack = client.get_sandbox(self.sandbox.allocation_unit.get_stack_name())
        user_private_key = os.path.join(ANSIBLE_DOCKER_SSH_DIR.bind,
                                        USER_PRIVATE_KEY_FILENAME)
        user_public_key = os.path.join(ANSIBLE_DOCKER_SSH_DIR.bind,
                                       USER_PUBLIC_KEY_FILENAME)
        inventory = Inventory(stack, top_def, user_private_key, user_public_key)

        inventory_path = os.path.join(self.directory, ANSIBLE_INVENTORY_FILENAME)
        self.save_file(inventory_path, inventory.serialize())

        return inventory_path

    def run_docker_container(self) -> None:
        ssh_directory = self.prepare_ssh_dir()
        inventory_path = self.prepare_inventory_file()

        try:
            container = ansible_service.AnsibleRunDockerContainer(
                settings.KYPO_CONFIG.ansible_docker_image, self.stage.repo_url,
                self.stage.rev, ssh_directory, inventory_path
            )
            DockerContainer.objects.create(stage=self.stage, container_id=container.id)

            for output in container.logs(stream=True):
                output = output.decode('utf-8')
                output = output[:-1] if output[-1] == '\n' else output
                AnsibleOutput.objects.create(stage=self.stage, content=output)

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


def get_stack_events(stack_name: str) -> List[Event]:
    """List all events in sandbox as Events objects."""
    client = utils.get_ostack_client()
    if stack_name in client.list_sandboxes():
        return client.list_sandbox_events(stack_name)
    return []


def get_stack_resources(stack_name: str) -> List[Resource]:
    """List all resources in sandbox as Resource objects."""
    client = utils.get_ostack_client()
    if stack_name in client.list_sandboxes():
        return client.list_sandbox_resources(stack_name)
    return []
