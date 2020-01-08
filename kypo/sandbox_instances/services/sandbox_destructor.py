import django_rq
import structlog
from django.utils import timezone
from django.core.exceptions import ObjectDoesNotExist

from ...sandbox_common import utils, exceptions
from ...sandbox_common.config import config

from ..models import CleanupRequest, SandboxAllocationUnit, StackCleanupStage
from ...sandbox_ansible_runs.models import AnsibleCleanupStage

LOG = structlog.get_logger()


def cleanup_sandbox_request(allocation_unit: SandboxAllocationUnit) -> CleanupRequest:
    """Create cleanup request and enqueue it."""
    try:
        sandbox = allocation_unit.sandbox
    except ObjectDoesNotExist:
        sandbox = None

    if sandbox and sandbox.lock:
        raise exceptions.ValidationError('Sandbox ID={} is locked.'.format(sandbox.id))

    if any([stage.is_running for stage in
            allocation_unit.allocation_request.stages.all()]):
        raise exceptions.ValidationError(
            'Create sandbox allocation request ID={} has not finished yet.'.
            format(allocation_unit.allocation_request.id)
        )

    request = CleanupRequest.objects.create(allocation_unit=allocation_unit)
    LOG.info('CleanupRequest created', request=request,
             allocation_unit=allocation_unit, sandbox=sandbox)
    enqueue_request(request, allocation_unit)
    return request


def enqueue_request(request: CleanupRequest,
                    allocation_unit: SandboxAllocationUnit) -> None:
    """Enqueue given request."""
    stg1 = StackCleanupStage.objects.create(request=request)
    queue = django_rq.get_queue(config.OPENSTACK_QUEUE,
                                default_timeout=config.SANDBOX_DELETE_TIMEOUT)
    queue.enqueue(StackCleanupStageManager().run, stage=stg1,
                  allocation_unit=allocation_unit)


class StackCleanupStageManager:
    def __init__(self):
        self._client = None

    @property
    def client(self):
        if not self._client:
            self._client = utils.get_ostack_client()
        return self._client

    def run(self, stage: StackCleanupStage, allocation_unit: SandboxAllocationUnit) -> None:
        """Run the stage."""
        try:
            stage.start = timezone.now()
            stage.save()
            LOG.info('StackCleanupStage started', stage=stage, allocation_unit=allocation_unit)
            self.delete_sandbox(allocation_unit)
        except Exception as ex:
            stage.mark_failed(ex)
            raise
        finally:
            stage.end = timezone.now()
            stage.save()

    def delete_sandbox(self, allocation_unit: SandboxAllocationUnit) -> None:
        """Deletes given sandbox. Hard specifies whether to use hard delete.
        On soft delete raises ValidationError if any sandbox is locked."""
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
        def sandbox_delete_check():
            stacks = self.client.list_sandboxes()
            if stack_name in stacks:
                stack_status = stacks[stack_name].stack_status
                return stack_status.endswith('FAILED')
            return True

        utils.wait_for(sandbox_delete_check, config.SANDBOX_DELETE_TIMEOUT, freq=10, initial_wait=3,
                       errmsg='Sandbox deletion exceeded timeout of {} sec. Sandbox: {}'
                       .format(config.SANDBOX_BUILD_TIMEOUT, str(stack_name)))


class AnsibleCleanupStageManager:
    def run(self, stage: AnsibleCleanupStage, allocation_unit: SandboxAllocationUnit) -> None:
        """Run the stage."""
        try:
            stage.start = timezone.now()
            stage.save()
            LOG.info('AnsibleCleanupStage started', stage=stage, allocation_unit=allocation_unit)
            self.delete_ansible(allocation_unit)
        except Exception as ex:
            stage.mark_failed(ex)
            raise
        finally:
            stage.end = timezone.now()
            stage.save()

    def delete_ansible(allocation_unit):
        """Delete Ansible container."""
        pass


def delete_allocation_unit(allocation_unit: SandboxAllocationUnit) -> None:
    allocation_unit.delete()
    LOG.info('Allocation Unit deleted from DB', allocation_unit=allocation_unit)
