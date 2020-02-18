import django_rq
import structlog
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone

from ..models import CleanupRequest, SandboxAllocationUnit, StackCleanupStage
from .sandbox_creator import OPENSTACK_QUEUE

from ...sandbox_ansible_app.lib import ansible_service
from ...sandbox_ansible_app.models import AnsibleCleanupStage
from ...sandbox_common_lib import utils, exceptions
from ...sandbox_common_lib.config import KypoConfigurationManager as kcm

LOG = structlog.get_logger()


def cleanup_sandbox_request(allocation_unit: SandboxAllocationUnit) -> CleanupRequest:
    """Create cleanup request and enqueue it."""
    try:
        sandbox = allocation_unit.sandbox
    except ObjectDoesNotExist:
        sandbox = None

    if sandbox and hasattr(sandbox, 'lock'):
        raise exceptions.ValidationError('Sandbox ID={} is locked.'.format(sandbox.id))

    # TODO: allow delete while still running
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
    alloc_stages = allocation_unit.allocation_request.stages.all().select_subclasses()
    stg1 = StackCleanupStage.objects.create(request=request, allocation_stage=alloc_stages[0])
    queue_openstack = django_rq.get_queue(OPENSTACK_QUEUE,
                                          default_timeout=kcm.config.SANDBOX_DELETE_TIMEOUT)
    result_openstack = queue_openstack.enqueue(StackCleanupStageManager().run, stage=stg1,
                                               allocation_unit=allocation_unit)

    # TODO: create and enqueue remaining stages

    queue_default = django_rq.get_queue()
    queue_default.enqueue(delete_allocation_unit, allocation_unit=allocation_unit,
                          depends_on=result_openstack)


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
        success, msg = self.client.wait_for_stack_delete_action(stack_name)
        if not success:
            raise exceptions.StackError(f'Stack {stack_name} delete failed: {msg}')


class AnsibleCleanupStageManager:
    def __init__(self, stage: AnsibleCleanupStage,
                 allocation_unit: SandboxAllocationUnit):
        self.stage = stage
        self.allocation_unit = allocation_unit

    def run(self) -> None:
        """Run the stage."""
        try:
            self.stage.start = timezone.now()
            self.stage.save()
            LOG.info('AnsibleCleanupStage started', stage=self.stage,
                     allocation_unit=self.allocation_unit)
            self.delete_ansible()
        except Exception as ex:
            self.stage.mark_failed(ex)
            raise
        finally:
            self.stage.end = timezone.now()
            self.stage.save()

    def delete_ansible(self):
        """Delete Ansible container."""
        ansible_service.delete_docker_container(
            self.stage.allocation_stage.container.container_id)


def delete_allocation_unit(allocation_unit: SandboxAllocationUnit) -> None:
    allocation_unit.delete()
    LOG.info('Allocation Unit deleted from DB', allocation_unit=allocation_unit)
