import django_rq
import structlog
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone
from django.conf import settings

from kypo.sandbox_instance_app.models import CleanupRequest, SandboxAllocationUnit, StackCleanupStage
from kypo.sandbox_instance_app.lib import sandbox_creator
from kypo.sandbox_instance_app.lib.sandbox_creator import OPENSTACK_QUEUE
from kypo.sandbox_ansible_app.lib import ansible_service
from kypo.sandbox_ansible_app.models import AnsibleCleanupStage
from kypo.sandbox_common_lib import utils, exceptions

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
                                          default_timeout=settings.KYPO_CONFIG.sandbox_delete_timeout)
    result_openstack = queue_openstack.enqueue(sandbox_creator.StackStageHandler().cleanup, stage=stg1)

    # TODO: create and enqueue remaining stages

    queue_default = django_rq.get_queue()
    queue_default.enqueue(delete_allocation_unit, allocation_unit=allocation_unit,
                          depends_on=result_openstack)


def delete_allocation_unit(allocation_unit: SandboxAllocationUnit) -> None:
    allocation_unit.delete()
    LOG.info('Allocation Unit deleted from DB', allocation_unit=allocation_unit)
