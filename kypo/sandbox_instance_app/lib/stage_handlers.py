import os
from typing import Callable

import docker.errors
import rq
import structlog
from django.conf import settings
from django.utils import timezone
from kypo.openstack_driver.exceptions import KypoException
from requests import exceptions as requests_exceptions

from kypo.sandbox_ansible_app.lib.ansible import AnsibleDockerRunner
from kypo.sandbox_ansible_app.models import AnsibleAllocationStage, AnsibleCleanupStage,\
    DockerContainer, AnsibleOutput
from kypo.sandbox_common_lib import utils, exceptions
from kypo.sandbox_definition_app.lib import definitions
from kypo.sandbox_instance_app.lib import jobs
from kypo.sandbox_instance_app.models import StackAllocationStage, Sandbox, StackCleanupStage,\
    HeatStack, SandboxAllocationUnit, Stage

LOG = structlog.get_logger()


class StageHandler:
    @staticmethod
    def run_stage(stage_name: str, func: Callable, stage: Stage, *args, **kwargs) -> \
            None:
        """Run the stage."""
        try:
            stage.start = timezone.now()
            stage.save()
            LOG.info(f'Stage {stage_name} started', stage=stage)
            func(stage, *args, **kwargs)
        except Exception as ex:
            stage.mark_failed(ex)
            raise
        finally:
            stage.end = timezone.now()
            stage.save()

    @staticmethod
    def lock_job(timeout=60, step=5):
        job = rq.get_current_job()
        jobs.lock_job(job, timeout, step)


class StackStageHandler(StageHandler):
    def __init__(self):
        self._client = None

    @property
    def client(self):
        if not self._client:
            self._client = utils.get_ostack_client()
        return self._client

    def build(self, stage_name: str, stage: StackAllocationStage, sandbox: Sandbox) -> None:
        """Run the stage."""
        try:
            self.lock_job()
        except Exception as ex:
            stage.mark_failed(ex)
            stage.end = timezone.now()
            stage.save()
            raise

        self.run_stage(stage_name, self.build_stack, stage, sandbox)

    def cancel(self, stage: StackAllocationStage) -> None:
        """Stop running stage."""
        jobs.delete_job(stage.process.process_id)
        if stage.start:
            self.delete_sandbox(stage.request.allocation_unit, wait=False)
        stage.mark_failed()

    def cleanup(self, stage_name: str, stage: StackCleanupStage) -> None:
        """Clean up stage resources."""
        self.run_stage(stage_name,
                       lambda stg: self.delete_sandbox(stg.request.allocation_unit),
                       stage)

    def build_stack(self, stage: StackAllocationStage, sandbox: Sandbox) -> None:
        """Build sandbox in OpenStack."""
        definition = sandbox.allocation_unit.pool.definition
        top_def = definitions.get_definition(definition.url, definition.rev, settings.KYPO_CONFIG)
        stack = self.client.create_sandbox(
            sandbox.allocation_unit.get_stack_name(), top_def,
            kp_name=stage.request.allocation_unit.pool.get_keypair_name())

        HeatStack.objects.create(stage=stage, stack_id=stack['stack']['id'])

        self.wait_for_stack_creation(stage)

    def wait_for_stack_creation(self, stage: StackAllocationStage) -> None:
        """Wait for stack creation."""
        name = stage.request.allocation_unit.get_stack_name()
        success, msg = self.client.wait_for_stack_create_action(name)
        if not success:
            roll_succ, roll_msg = self.client.wait_for_stack_rollback_action(name)
            if not roll_succ:
                LOG.warning('Rollback failed', msg=roll_msg)
            raise exceptions.StackError(f'Sandbox build failed: {msg}')

        LOG.info("Stack created successfully", stage=stage)

    def delete_sandbox(self, allocation_unit: SandboxAllocationUnit, wait: bool = True) -> None:
        """Delete given sandbox. Wait for completion if `wait` is True."""
        stack_name = allocation_unit.get_stack_name()

        LOG.debug('Starting Stack delete in OpenStack', stack_name=stack_name,
                  allocation_unit=allocation_unit)

        try:
            self.client.delete_sandbox(stack_name)
        except KypoException as ex:
            # Sandbox is already deleted.
            LOG.warning('Deleting sandbox failed', exception=str(ex),
                        allocation_unit=allocation_unit)
            return

        if wait:
            self.wait_for_stack_deletion(stack_name)
            LOG.debug('Stack deleted successfully from OpenStack',
                      stack_name=stack_name, allocation_unit=allocation_unit)

    def wait_for_stack_deletion(self, stack_name: str) -> None:
        """Wait for stack deletion."""
        success, msg = self.client.wait_for_stack_delete_action(stack_name)
        if not success:
            raise exceptions.StackError(f'Stack {stack_name} delete failed: {msg}')

    def update_allocation_stage(self, stage: StackAllocationStage) -> StackAllocationStage:
        """Update stage with current stack status from OpenStack."""
        sandboxes = self.client.list_sandboxes()
        stack_name = stage.request.allocation_unit.get_stack_name()
        if stack_name in sandboxes:
            sb = sandboxes[stack_name]
            stage.status = sb.stack_status
            stage.status_reason = sb.stack_status_reason
        else:
            stage.status = None
            stage.status_reason = None
        stage.save()
        return stage


class AnsibleStageHandler(StageHandler):
    def build(self, stage_name: str, stage: AnsibleAllocationStage, sandbox: Sandbox) -> None:
        """Run the stage."""
        self.run_stage(stage_name, self.run_docker_container, stage, sandbox)

    # noinspection PyMethodMayBeStatic
    def cancel(self, stage: AnsibleAllocationStage) -> None:
        """Stop running stage."""
        jobs.delete_job(stage.process.process_id)
        try:
            if hasattr(stage, 'container'):
                container = stage.container
                AnsibleDockerRunner().delete_container(container.container_id)
                container.delete()
        except docker.errors.NotFound as ex:
            LOG.warning('Cancelling Ansible', exception=str(ex), stage=stage)
        stage.failed = True
        stage.save()

    def cleanup(self, stage_name: str, stage: AnsibleCleanupStage):
        """Clean up stage resources. Currently there is nothing to be done;
        only set the stage as finished.
        """
        self.run_stage(stage_name, lambda x: None, stage)

    @staticmethod
    def run_docker_container(stage: AnsibleAllocationStage, sandbox: Sandbox) -> None:
        """Prepare and run the Ansible."""
        dir_path = os.path.join(settings.KYPO_CONFIG.ansible_docker_volumes,
                                sandbox.allocation_unit.get_stack_name(),
                                f'{stage.id}-{utils.get_simple_uuid()}')
        runner = AnsibleDockerRunner()
        ssh_directory = runner.prepare_ssh_dir(dir_path, stage, sandbox, settings.KYPO_CONFIG)
        top_def = definitions.get_definition(
            stage.request.allocation_unit.pool.definition.url,
            stage.request.allocation_unit.pool.definition.rev,
            settings.KYPO_CONFIG
        )
        inventory_path = runner.prepare_inventory_file(dir_path, sandbox, top_def)

        try:
            container = AnsibleDockerRunner().run_container(
                settings.KYPO_CONFIG.ansible_docker_image, stage.repo_url,
                stage.rev, ssh_directory, inventory_path
            )
            DockerContainer.objects.create(stage=stage, container_id=container.id)

            for output in container.logs(stream=True):
                output = output.decode('utf-8')
                output = output[:-1] if output[-1] == '\n' else output
                AnsibleOutput.objects.create(stage=stage, content=output)

            status = container.wait(timeout=60)
            container.remove()

        except (docker.errors.APIError,
                docker.errors.DockerException,
                requests_exceptions.ReadTimeout) as ex:
            raise exceptions.DockerError(ex)

        status_code = status['StatusCode']
        if status_code != 0:
            raise exceptions.AnsibleError('Ansible ID={} failed with status code \'{}\''
                                          .format(stage.id, status_code))
