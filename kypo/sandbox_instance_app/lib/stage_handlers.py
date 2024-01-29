import abc
import os
import signal
from typing import Type

import docker.errors
import structlog
from django.conf import settings
from django.utils import timezone
from kypo.cloud_commons import KypoException, StackCreationFailed
from redis import Redis
from rq.exceptions import NoSuchJobError
from rq.job import Job

from kypo.sandbox_ansible_app.lib.ansible import CleanupAnsibleRunner, \
    AllocationAnsibleRunner, AnsibleRunner
from kypo.sandbox_ansible_app.models import AnsibleAllocationStage, AnsibleCleanupStage, \
    Container, UserAnsibleCleanupStage, CleanupStage, ContainerCleanup
from kypo.sandbox_common_lib import utils, exceptions
from kypo.sandbox_definition_app.lib import definitions
from kypo.sandbox_instance_app.models import Sandbox, TerraformStack, \
    SandboxAllocationUnit, StackAllocationStage, StackCleanupStage, \
    RQJob, AllocationRQJob, CleanupRQJob, AllocationTerraformOutput, CleanupTerraformOutput

LOG = structlog.get_logger()
ALLOCATION_JOB_NAME = 'ansible-allocation-{}'
CLEANUP_JOB_NAME = 'ansible-cleanup-{}'


class StageHandler(abc.ABC):
    """
    Handles DB Stage object and generalizes its common tasks.

    WARNING: Always set _job_class attribute with type inherited from RQJob
      in all non-abstract descendants.
    """
    _job_class: Type[RQJob]

    def __init__(self, stage, name: str = None):
        self.stage = stage
        self.name = name if name is not None else self.stage.__class__.__name__

    def execute(self) -> None:
        """
        Handles stage execution defined in method _execute.

        Sets the start and the end time of the stage execution, saves any error messages
          of all caught exceptions, and re-raise them again.
        Warning: Do not override this method. Any changes should be made to _execute method.
        """
        try:
            LOG.info(f'Stage {self.name} started', stage=self.stage)
            self.stage.start = timezone.now()
            self.stage.save()
            return self._execute()
        except Exception as ex:
            self.stage.failed = True
            self.stage.error_message = str(ex)
            raise
        finally:
            self.stage.end = timezone.now()
            self.stage.finished = True
            self.stage.save()
            LOG.info(f'Stage {self.name} ended', stage=self.stage)

    def set_job_id(self, job_id: str) -> None:
        """
        Set Job ID once execution of this stage is enqueued.

        :param job_id: The ID of enqueues Job that will execute this stage.
        """
        if hasattr(self._job_class, 'allocation_stage'):
            self._job_class.objects.create(allocation_stage=self.stage, job_id=job_id)
        elif hasattr(self._job_class, 'cleanup_stage'):
            self._job_class.objects.create(cleanup_stage=self.stage, job_id=job_id)
        else:
            LOG.warning(f'Unknown Job class \'{self._job_class}\'. Job ID \'{job_id}\' was not set')

    @abc.abstractmethod
    def _execute(self) -> None:
        """
        Execute the stage.
        """
        pass

    def cancel(self) -> None:
        """
        Handles stage cancellation defined in method _cancel.

        Stops the stage execution, sets the stage as failed, sets its end time of execution,
          saves any error messages of caught exceptions during cancellation,
          and re-raise them again.
        Warning: Do not override this method. Any changes should be made to _cancel method.
        """
        if not self.stage.finished:
            try:
                LOG.info(f'Cancellation of stage {self.name} started', stage=self.stage)
                self._delete_job()
                return self._cancel()
            except Exception as ex:
                self.stage.error_message = str(ex)
                raise
            finally:
                self.stage.failed = True
                self.stage.end = timezone.now()
                self.stage.finished = True
                self.stage.save()
                LOG.info(f'Cancellation of stage {self.name} ended', stage=self.stage)

    def _delete_job(self) -> None:
        """
        Remove and delete enqueued Job of the stage execution from a queue.
        """
        if hasattr(self.stage, 'rq_job'):
            try:
                Job.fetch(self.stage.rq_job.job_id,
                          connection=Redis(host=settings.KYPO_CONFIG.redis.host))\
                    .delete(delete_dependents=True)
            except NoSuchJobError:  # Job already deleted
                pass
        else:
            LOG.warning(f'Stage {self.name} does not have an RQ job')

    @abc.abstractmethod
    def _cancel(self) -> None:
        """
        Cancel the stage
        """
        pass


class StackStageHandler(StageHandler):
    """
    Generalizes common tasks of stages manipulating with OpenStack stacks.
    """
    _client = utils.get_terraform_client()

    @abc.abstractmethod
    def _execute(self) -> None:
        pass

    @abc.abstractmethod
    def _cancel(self) -> None:
        pass

    def _log_process_output(self, process, terraform_output, **kwargs):
        output = self._client.get_process_output(process)
        for line in output:
            line = line.rstrip()
            LOG.debug(line)
            terraform_output.objects.create(**kwargs, content=line)

    def _wait_for_process(self, process, terraform_output,
                          timeout=settings.KYPO_CONFIG.sandbox_build_timeout, **kwargs):
        """
        Wait for process to finish.
        """
        stdout, stderr, return_code = self._client.wait_for_process(process, timeout)
        if return_code:
            LOG.error('Terraform execution failed', stderr=stderr, **kwargs)
            terraform_output.objects.create(**kwargs, content=stderr)
            raise KypoException(f'Terraform execution failed. See logs for details.')

    def _delete_stack(self, allocation_unit: SandboxAllocationUnit, log_output: bool = True)\
            -> None:
        """
        Delete stack associated with the given allocation unit.
        """
        stack_name = allocation_unit.get_stack_name()

        LOG.debug('Starting Stack delete in OpenStack', stack_name=stack_name,
                  allocation_unit=allocation_unit)

        try:
            process = self._client.delete_stack(stack_name)
            if process:
                if log_output:
                    self._log_process_output(process, CleanupTerraformOutput,
                                             cleanup_stage=self.stage)
                self._wait_for_process(process, CleanupTerraformOutput, cleanup_stage=self.stage)
            else:
                # process is None when delete_stack is not able to initialize stack directory,
                # but it is not a problem because creation failed to initialize as well
                LOG.warning('The deletion of the stack failed.'
                            ' Terraform could not initialize directory')
        except KypoException as exc:
            raise exceptions.StackError(f'Sandbox deletion failed :{exc}')

        try:
            self._client.delete_terraform_workspace(stack_name)
        except KypoException as exc:
            LOG.warning(f'Terraform workspace deletion failed :{exc}')

        LOG.debug('Deleting local terraform stack directory', stack_name=stack_name,
                  allocation_unit=allocation_unit)
        self._client.delete_stack_directory(stack_name)


class AllocationStackStageHandler(StackStageHandler):
    """
    Specifies tasks needed for OpenStack stack allocation and its cancellation.
    """
    stage: StackAllocationStage
    _job_class: Type[AllocationRQJob] = AllocationRQJob

    def __init__(self, stage):
        self.process = None
        super().__init__(stage)

    def _execute(self) -> None:
        """
        Allocate stack in the OpenStack cloud platform.
        """
        allocation_unit = self.stage.allocation_request.allocation_unit
        stack_name = allocation_unit.get_stack_name()
        pool = allocation_unit.pool
        definition = pool.definition
        top_def = definitions.get_definition(definition.url, pool.rev_sha, settings.KYPO_CONFIG)
        try:
            self.process = self._client.create_stack(
                top_def, stack_name=stack_name,
                key_pair_name_ssh=allocation_unit.pool.ssh_keypair_name,
                key_pair_name_cert=allocation_unit.pool.certificate_keypair_name,
            )
            TerraformStack.objects.create(allocation_stage=self.stage, stack_id=self.process.pid)
            self._log_process_output(self.process, AllocationTerraformOutput,
                                     allocation_stage=self.stage)
            self._wait_for_process(self.process, AllocationTerraformOutput,
                                   allocation_stage=self.stage)
        except KypoException as exc:
            if self.process:
                self.process.terminate()
            super()._delete_stack(allocation_unit, log_output=False)
            raise StackCreationFailed(f'Sandbox build failed: {exc}')

    def _cancel(self) -> None:
        """
        Stop the OpenStack stack allocation and remove what has been allocated.
        """
        try:
            if self.stage.start and hasattr(self.stage, 'terraformstack'):
                process_id = int(self.stage.terraformstack.stack_id)
                os.kill(process_id, signal.SIGTERM)
        except ProcessLookupError:
            return


class CleanupStackStageHandler(StackStageHandler):
    """
    Specifies tasks needed for OpenStack stack deletion and its cancellation.
    """
    stage: StackCleanupStage
    _job_class: Type[CleanupRQJob] = CleanupRQJob

    def _execute(self) -> None:
        """
        Delete allocated stack in the OpenStack platform.
        """
        self._delete_stack(self.stage.cleanup_request.allocation_unit)

    def _cancel(self) -> None:
        """
        Stop the deletion of the OpenStack stack.

        INFO: Nothing to be done. Deletion is irreversible operation.
        """
        pass


class AnsibleStageHandler(StageHandler):
    """
    Generalizes common tasks of stages executing Ansible tasks on the remote infrastructure.
    """

    def __init__(self, stage: [AnsibleCleanupStage, AnsibleAllocationStage], name: str = None):
        super().__init__(stage, name)
        self.stage = stage

    @abc.abstractmethod
    def _execute(self) -> None:
        pass

    @abc.abstractmethod
    def _cancel(self) -> None:
        pass

    def create_directory_path(self, allocation_unit: SandboxAllocationUnit):
        """
        Compose absolute path to directory for Docker container volumes.
        """
        return os.path.join(settings.KYPO_CONFIG.ansible_runner_settings.volumes_path,
                            allocation_unit.get_stack_name(),
                            f'{self.stage.id}-{utils.get_simple_uuid()}')

    def check_status(self, status: dict):
        """
        Check status returned by Docker container
        and raise an exception if Ansible execution failed.
        """
        status_code = status['StatusCode']
        if status_code != 0:
            raise exceptions.AnsibleError('Ansible ID={} failed with status code \'{}\''
                                          .format(self.stage.id, status_code))


class AllocationAnsibleStageHandler(AnsibleStageHandler):
    """
    Specifies tasks needed for Ansible execution on the remote infrastructure and its cancellation.
    """
    stage: AnsibleAllocationStage
    _job_class: Type[AllocationRQJob] = AllocationRQJob

    def __init__(self, stage: AnsibleAllocationStage, sandbox: Sandbox = None, name: str = None):
        super().__init__(stage, name)

        self.allocation_unit = stage.allocation_request_fk_many.allocation_unit
        self.directory_path = self.create_directory_path(self.allocation_unit)
        self.sandbox = sandbox

    def _execute(self) -> None:
        """
        Prepare and execute the Ansible playbooks on the remote infrastructure.
        """
        if self.sandbox is None:
            raise exceptions.AnsibleError(f'Sandbox was not provided')

        runner = AllocationAnsibleRunner(self.directory_path)
        runner.prepare_ssh_dir(self.allocation_unit.pool, self.sandbox)
        runner.prepare_inventory_file(self.sandbox)
        runner.prepare_containers_directory(self.sandbox)
        runner.prepare_git_credentials()

        container = runner.run_ansible_playbook(self.stage.repo_url, self.stage.rev, self.stage)
        try:
            Container.objects.create(allocation_stage=self.stage,
                                     container_name=container.get_container_name())

            container.get_container_outputs()
            container.check_container_status()
        finally:
            container.delete()

    def _cancel(self) -> None:
        """
        Stop the Ansible execution.
        """
        try:
            if hasattr(self.stage, 'container'):
                container = self.stage.container
                AnsibleRunner(self.directory_path).delete_container(container.container_name)
                container.delete()
        except docker.errors.NotFound as ex:
            LOG.warning('Cancelling Ansible', exception=str(ex), stage=self.stage)


class CleanupAnsibleStageHandler(AnsibleStageHandler):
    """
    Specifies tasks needed for resources cleanup created during the Ansible execution.
    """
    stage: CleanupStage
    _job_class: Type[CleanupRQJob] = CleanupRQJob

    def __init__(self, stage: CleanupStage):
        super().__init__(stage)

        self.allocation_unit = stage.cleanup_request_fk_many.allocation_unit
        self.directory_path = self.create_directory_path(self.allocation_unit)

    def _execute(self) -> None:
        """
        Clean up resources created during the Ansible execution.
        """
        if isinstance(self.stage, UserAnsibleCleanupStage):
            return
        runner = CleanupAnsibleRunner(self.directory_path)
        runner.prepare_ssh_dir(self.allocation_unit.pool)
        runner.prepare_inventory_file(self.allocation_unit)
        runner.prepare_git_credentials()

        allocation_request = self.allocation_unit.allocation_request
        allocation_stage = allocation_request.networkingansibleallocationstage

        container = runner.run_ansible_playbook(allocation_stage.repo_url, allocation_stage.rev,
                                                self.stage, cleanup=True)
        try:
            ContainerCleanup.objects.create(cleanup_stage=self.stage,
                                            container_name=container.get_container_name())
            container.get_container_outputs()
            container.check_container_status()
        finally:
            container.delete()

    def _cancel(self) -> None:
        """
        Stop the resources clean up.

        INFO: Nothing to be done. The clean up is irreversible operation.
        """
        pass
