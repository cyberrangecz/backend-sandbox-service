import os
import docker.errors
import structlog
import abc
from typing import Type
from django.conf import settings
from django.utils import timezone
from requests import exceptions as requests_exceptions
from redis import Redis
from rq.exceptions import NoSuchJobError
from rq.job import Job

from kypo.openstack_driver.exceptions import KypoException

from kypo.sandbox_ansible_app.lib.ansible import CleanupAnsibleDockerRunner,\
    AllocationAnsibleDockerRunner, AnsibleDockerRunner
from kypo.sandbox_ansible_app.models import AnsibleAllocationStage, AnsibleCleanupStage,\
    DockerContainer, AllocationAnsibleOutput, CleanupAnsibleOutput, UserAnsibleCleanupStage,\
    CleanupStage, DockerContainerCleanup
from kypo.sandbox_common_lib import utils, exceptions
from kypo.sandbox_definition_app.lib import definitions

from kypo.sandbox_instance_app.models import Sandbox, HeatStack,\
    SandboxAllocationUnit, StackAllocationStage, StackCleanupStage,\
    RQJob, AllocationRQJob, CleanupRQJob

LOG = structlog.get_logger()


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
    _client = utils.get_ostack_client()

    @abc.abstractmethod
    def _execute(self) -> None:
        pass

    @abc.abstractmethod
    def _cancel(self) -> None:
        pass

    def _delete_sandbox(self, allocation_unit: SandboxAllocationUnit) -> None:
        """
        Delete sandbox associated with the given allocation unit
          and wait for its completion if wait parameter is True.
        """
        stack_name = allocation_unit.get_stack_name()

        LOG.debug('Starting Stack delete in OpenStack', stack_name=stack_name,
                  allocation_unit=allocation_unit)

        try:
            self._client.delete_stack(stack_name)
        except KypoException as ex:
            # Sandbox is already deleted.
            LOG.warning('Deleting sandbox failed', exception=str(ex),
                        allocation_unit=allocation_unit)
            return


class AllocationStackStageHandler(StackStageHandler):
    """
    Specifies tasks needed for OpenStack stack allocation and its cancellation.
    """
    stage: StackAllocationStage
    _job_class: Type[AllocationRQJob] = AllocationRQJob

    def _execute(self) -> None:
        """
        Allocate stack in the OpenStack cloud platform.
        """
        allocation_unit = self.stage.allocation_request.allocation_unit
        pool = allocation_unit.pool
        definition = pool.definition
        top_def = definitions.get_definition(definition.url, pool.rev_sha, settings.KYPO_CONFIG)
        stack = self._client.create_stack(
            allocation_unit.get_stack_name(), top_def,
            key_pair_name_ssh=allocation_unit.pool.ssh_keypair_name,
            key_pair_name_cert=allocation_unit.pool.certificate_keypair_name,
        )

        HeatStack.objects.create(allocation_stage=self.stage, stack_id=stack['stack']['id'])

        self._wait_for_stack_creation()

    def _wait_for_stack_creation(self) -> None:
        """
        Wait for the stack creation.
        """
        name = self.stage.allocation_request.allocation_unit.get_stack_name()
        success, msg = self._client.wait_for_stack_create_action(name)
        if not success:
            roll_succ, roll_msg = self._client.wait_for_stack_rollback_action(name)
            if not roll_succ:
                LOG.warning('Rollback failed', msg=roll_msg)
            raise exceptions.StackError(f'Sandbox build failed: {msg}')

        LOG.info("Stack created successfully", stage=self.stage)

    def _cancel(self) -> None:
        """
        Stop the OpenStack stack allocation and remove what has been allocated.
        """
        if self.stage.start:
            self._delete_sandbox(self.stage.allocation_request.allocation_unit)

    def update_allocation_stage(self) -> StackAllocationStage:
        """
        Update stage with current stack status from the OpenStack platform.
        """
        # TODO get stack status directly!
        stacks = self._client.list_stacks()
        stack_name = self.stage.allocation_request.allocation_unit.get_stack_name()
        if stack_name in stacks:
            sb = stacks[stack_name]
            self.stage.status = sb.stack_status
            self.stage.status_reason = sb.stack_status_reason
        else:
            self.stage.status = None
            self.stage.status_reason = None
        self.stage.save()
        return self.stage


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
        self._delete_sandbox(self.stage.cleanup_request.allocation_unit)

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
        return os.path.join(settings.KYPO_CONFIG.ansible_docker_volumes,
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

        runner = AllocationAnsibleDockerRunner(self.directory_path)
        runner.prepare_ssh_dir(self.allocation_unit.pool, self.sandbox)
        runner.prepare_inventory_file(self.sandbox)

        try:
            container = runner.run_container(self.stage.repo_url, self.stage.rev)
            DockerContainer.objects.create(allocation_stage=self.stage, container_id=container.id)

            for output in container.logs(stream=True):
                output = output.decode('utf-8')
                output = output[:-1] if output[-1] == '\n' else output
                AllocationAnsibleOutput.objects.create(allocation_stage=self.stage, content=output)

            status = container.wait(timeout=settings.KYPO_CONFIG.sandbox_ansible_timeout)
            container.remove()
        except (docker.errors.APIError,
                docker.errors.DockerException,
                requests_exceptions.ReadTimeout) as ex:
            raise exceptions.DockerError(ex)

        self.check_status(status)

    def _cancel(self) -> None:
        """
        Stop the Ansible execution.
        """
        try:
            if hasattr(self.stage, 'dockercontainer'):
                container = self.stage.dockercontainer
                AnsibleDockerRunner(self.directory_path).delete_container(container.container_id)
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
        runner = CleanupAnsibleDockerRunner(self.directory_path)
        runner.prepare_ssh_dir(self.allocation_unit.pool)
        runner.prepare_inventory_file(self.allocation_unit)

        allocation_request = self.allocation_unit.allocation_request
        allocation_stage = allocation_request.networkingansibleallocationstage

        try:
            container = runner.run_container(allocation_stage.repo_url, allocation_stage.rev,
                                             ansible_cleanup=True)
            DockerContainerCleanup.objects.create(cleanup_stage=self.stage,
                                                  container_id=container.id)

            for output in container.logs(stream=True):
                output = output.decode('utf-8')
                output = output[:-1] if output[-1] == '\n' else output
                CleanupAnsibleOutput.objects.create(cleanup_stage=self.stage, content=output)

            status = container.wait(timeout=settings.KYPO_CONFIG.sandbox_ansible_timeout)
            container.remove()
        except (docker.errors.APIError,
                docker.errors.DockerException,
                requests_exceptions.ReadTimeout) as ex:
            raise exceptions.DockerError(ex)

        self.check_status(status)

    def _cancel(self) -> None:
        """
        Stop the resources clean up.

        INFO: Nothing to be done. The clean up is irreversible operation.
        """
        pass
