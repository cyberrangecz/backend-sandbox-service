import os
import shutil
import time
from typing import Callable

import docker.errors
import rq
import structlog
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone
from requests import exceptions as requests_exceptions
from rq.job import Job

from kypo.sandbox_ansible_app.lib.ansible_service import AnsibleDockerRunner, \
    ANSIBLE_DOCKER_SSH_DIR
from kypo.sandbox_ansible_app.lib.inventory import Inventory
from kypo.sandbox_ansible_app.models import AnsibleAllocationStage, AnsibleCleanupStage,\
    DockerContainer, AnsibleOutput
from kypo.sandbox_common_lib import utils, exceptions
from kypo.sandbox_definition_app.lib import definition_service
from kypo.sandbox_instance_app.lib import sandbox_service
from kypo.sandbox_instance_app.models import StackAllocationStage, Sandbox, StackCleanupStage,\
    HeatStack, SandboxAllocationUnit, Stage

ANSIBLE_INVENTORY_FILENAME = 'inventory.yml'
MNG_PRIVATE_KEY_FILENAME = 'pool_mng_key'
USER_PRIVATE_KEY_FILENAME = 'user_key'
USER_PUBLIC_KEY_FILENAME = 'user_key.pub'

LOG = structlog.get_logger()


class StageHandler:
    @staticmethod
    def run_stage(name: str, func: Callable, stage: Stage, *args, **kwargs) -> None:
        """Run the stage."""
        try:
            stage.start = timezone.now()
            stage.save()
            LOG.info(f'Stage {name} started', stage=stage)
            func(stage, *args, **kwargs)
        except Exception as ex:
            stage.mark_failed(ex)
            raise
        finally:
            stage.end = timezone.now()
            stage.save()

    @staticmethod
    def delete_job(job_id):
        Job.fetch(job_id).delete(delete_dependents=True)

    @staticmethod
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


class StackStageHandler(StageHandler):
    def __init__(self, stage_name=None):
        self.stage_name = stage_name
        self._client = None

    @property
    def client(self):
        if not self._client:
            self._client = utils.get_ostack_client()
        return self._client

    def build(self, stage: StackAllocationStage, sandbox: Sandbox) -> None:
        try:
            self.lock_job()
        except Exception as ex:
            stage.mark_failed(ex)
            stage.end = timezone.now()
            stage.save()
            raise

        self.run_stage(self.stage_name, self.build_stack, stage, sandbox)

    def stop(self, stage: StackAllocationStage) -> None:
        # TODO: check existence of sb and job
        self.delete_job(stage.process.process_id)
        if stage.start:
            self.delete_sandbox(stage.request.allocation_unit, wait=False)

    def cleanup(self, stage: StackCleanupStage) -> None:
        self.run_stage(self.stage_name,
                       lambda stg: self.delete_sandbox(stg.request.allocation_unit),
                       stage)

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

    def delete_sandbox(self, allocation_unit: SandboxAllocationUnit, wait=True) -> None:
        """Deletes given sandbox. Hard specifies whether to use hard delete.
        On soft delete raises ValidationError if any sandbox is locked."""
        stack_name = allocation_unit.get_stack_name()

        LOG.debug('Starting Stack delete in OpenStack',
                  stack_name=stack_name, allocation_unit=allocation_unit)

        self.client.delete_sandbox(stack_name)
        if wait:
            self.wait_for_stack_deletion(stack_name)

        LOG.info('Stack deleted successfully from OpenStack',
                 stack_name=stack_name, allocation_unit=allocation_unit)

    def wait_for_stack_deletion(self, stack_name: str) -> None:
        """Wait for stack deletion."""
        success, msg = self.client.wait_for_stack_delete_action(stack_name)
        if not success:
            raise exceptions.StackError(f'Stack {stack_name} delete failed: {msg}')

    def update_allocation_stage(self, stage: StackAllocationStage) -> StackAllocationStage:
        """Update stage with current stack status from OpenStack."""
        sandboxes = self.client.list_sandboxes()
        sb = sandboxes[stage.request.allocation_unit.get_stack_name()]
        stage.status = sb.stack_status
        stage.status_reason = sb.stack_status_reason
        stage.save()
        return stage


class AnsibleStageHandler(StageHandler):
    def __init__(self, stage_name) -> None:
        self.stage_name = stage_name

    def build(self, stage: AnsibleAllocationStage, sandbox: Sandbox) -> None:
        self.run_stage(self.stage_name, self.run_docker_container, stage, sandbox)

    def stop(self, stage: AnsibleAllocationStage) -> None:
        # TODO: check existence of container and job
        self.delete_job(stage.process.process_id)
        if stage.start:
            AnsibleDockerRunner().delete(stage.container.container_id)

    def cleanup(self, stage: AnsibleCleanupStage):
        """Only sets the stage values."""
        self.run_stage(self.stage_name, self.cleanup_logic, stage)

    def cleanup_logic(self, *args, **kwargs):
        """Currently just a dummy function for clean up."""
        pass

    def run_docker_container(self, stage: AnsibleAllocationStage, sandbox: Sandbox) -> None:
        dir_path = os.path.join(settings.KYPO_CONFIG.ansible_docker_volumes,
                                sandbox.allocation_unit.get_stack_name(),
                                f'{stage.id}-{utils.get_simple_uuid()}')
        ssh_directory = self.prepare_ssh_dir(dir_path, stage, sandbox)
        inventory_path = self.prepare_inventory_file(dir_path, stage, sandbox)

        try:
            container = AnsibleDockerRunner().run(
                settings.KYPO_CONFIG.ansible_docker_image, stage.repo_url,
                stage.rev, ssh_directory, inventory_path
            )
            DockerContainer.objects.create(stage=stage, container_id=container.id)

            for output in container.logs(stream=True):
                output = output.decode('utf-8')
                output = output[:-1] if output[-1] == '\n' else output
                AnsibleOutput.objects.create(stage=stage, content=output)

            status = container.wait(timeout=60)
        except (docker.errors.APIError,
                docker.errors.DockerException,
                requests_exceptions.ReadTimeout) as ex:
            raise exceptions.DockerError(ex)

        status_code = status['StatusCode']
        if status_code != 0:
            raise exceptions.AnsibleError('Ansible ID={} failed with status code \'{}\''
                                          .format(stage.id, status_code))

    @staticmethod
    def make_dir(dir_path: str) -> None:
        os.makedirs(dir_path, exist_ok=True)

    @staticmethod
    def save_file(file_path: str, data: str) -> None:
        with open(file_path, 'w') as file:
            file.write(data)

    def prepare_ssh_dir(self, dir_path: str, stage: AnsibleAllocationStage,
                        sandbox: Sandbox) -> str:
        """Prepare files that will be passed to docker container."""
        config = settings.KYPO_CONFIG
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

    def prepare_inventory_file(self, dir_path: str, stage: AnsibleAllocationStage,
                               sandbox: Sandbox) -> str:
        top_def = definition_service.get_definition(
            stage.request.allocation_unit.pool.definition.url,
            stage.request.allocation_unit.pool.definition.rev,
            f'rev-{stage.request.allocation_unit.pool.definition.rev}_stage-{stage.id}')

        client = utils.get_ostack_client()
        stack = client.get_sandbox(sandbox.allocation_unit.get_stack_name())
        user_private_key = os.path.join(ANSIBLE_DOCKER_SSH_DIR.bind,
                                        USER_PRIVATE_KEY_FILENAME)
        user_public_key = os.path.join(ANSIBLE_DOCKER_SSH_DIR.bind,
                                       USER_PUBLIC_KEY_FILENAME)
        inventory = Inventory(stack, top_def, user_private_key, user_public_key)

        inventory_path = os.path.join(dir_path, ANSIBLE_INVENTORY_FILENAME)
        self.save_file(inventory_path, inventory.serialize())

        return inventory_path
