from typing import List, Iterable

import django_rq
import structlog
from django.core.exceptions import ObjectDoesNotExist
from django.conf import settings

from kypo.sandbox_instance_app.lib import sandboxes
from kypo.sandbox_instance_app.lib.stage_handlers import StackStageHandler, AnsibleStageHandler
from kypo.sandbox_instance_app.models import CleanupRequest, SandboxAllocationUnit, \
    StackCleanupStage, AllocationRequest, Sandbox
from kypo.sandbox_instance_app.lib.sandbox_creator import OPENSTACK_QUEUE, ANSIBLE_QUEUE
from kypo.sandbox_common_lib import exceptions, utils
from kypo.sandbox_ansible_app.models import AnsibleCleanupStage

LOG = structlog.get_logger()


def create_cleanup_request(allocation_unit: SandboxAllocationUnit) -> CleanupRequest:
    """Create cleanup request and enqueue it. Immediately delete sandbox from database."""
    try:
        sandbox = allocation_unit.sandbox
    except ObjectDoesNotExist:
        sandbox = None
    else:
        if hasattr(sandbox, 'lock'):
            raise exceptions.ValidationError('Sandbox ID={} is locked.'.format(sandbox.id))

    if not allocation_unit.allocation_request.is_finished:
        raise exceptions.ValidationError(
            f'Create sandbox allocation request ID={allocation_unit.allocation_request.id}'
            f' has not finished yet. You need to cancel it first.'
        )

    request = CleanupRequest.objects.create(allocation_unit=allocation_unit)
    LOG.info('CleanupRequest created', request=request,
             allocation_unit=allocation_unit, sandbox=sandbox)

    if sandbox:
        sandbox.delete()
        sandboxes.clear_cache(sandbox)

    enqueue_cleanup_request(request, allocation_unit)
    return request


def create_cleanup_requests(allocation_units: List[SandboxAllocationUnit]) -> List[CleanupRequest]:
    """Batch version of create_cleanup_request."""
    return [create_cleanup_request(unit) for unit in allocation_units]


def enqueue_cleanup_request(request: CleanupRequest,
                            allocation_unit: SandboxAllocationUnit) -> None:
    """Enqueue given request."""
    alloc_stages = allocation_unit.allocation_request.stages.all().select_subclasses()

    stage_user_ans = AnsibleCleanupStage.objects.create(
        request=request, allocation_stage=alloc_stages[2]
    )
    queue_ansible = django_rq.get_queue(ANSIBLE_QUEUE)
    job_user_ans = queue_ansible.enqueue(
        AnsibleStageHandler().cleanup, stage_name='Cleanup User Ansible',
        stage=stage_user_ans)

    stage_networking = AnsibleCleanupStage.objects.create(
        request=request, allocation_stage=alloc_stages[1]
    )
    job_networking = queue_ansible.enqueue(
        AnsibleStageHandler().cleanup, stage_name='Cleanup Networking Ansible',
        stage=stage_networking, depends_on=job_user_ans)

    stage_stack = StackCleanupStage.objects.create(
        request=request, allocation_stage=alloc_stages[0]
    )
    queue_stack = django_rq.get_queue(OPENSTACK_QUEUE,
                                      default_timeout=settings.KYPO_CONFIG.sandbox_delete_timeout)
    job_stack = queue_stack.enqueue(
        StackStageHandler().cleanup, stage_name=stage_stack.__class__.__name__,
        stage=stage_stack,
        depends_on=job_networking)

    queue_default = django_rq.get_queue()
    queue_default.enqueue(delete_allocation_unit, allocation_unit=allocation_unit,
                          depends_on=job_stack)


def delete_allocation_unit(allocation_unit: SandboxAllocationUnit) -> None:
    allocation_unit.delete()
    LOG.info('Allocation Unit deleted from DB', allocation_unit=allocation_unit)


def cancel_allocation_request(alloc_req: AllocationRequest):
    """(Soft) cancel all stages of Allocation Request."""
    stages = alloc_req.stages.all().select_subclasses()
    if alloc_req.is_finished:
        raise exceptions.ValidationError(
            f'Allocation request ID {alloc_req.id} is finished and does not need cancelling.'
        )
    AnsibleStageHandler().cancel(stages[2])
    AnsibleStageHandler().cancel(stages[1])
    StackStageHandler().cancel(stages[0])
