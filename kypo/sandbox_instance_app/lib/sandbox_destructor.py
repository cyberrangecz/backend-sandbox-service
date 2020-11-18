from typing import List
import django_rq
import structlog
from django.core.exceptions import ObjectDoesNotExist
from django.conf import settings

from kypo.openstack_driver.exceptions import KypoException

from kypo.sandbox_common_lib import exceptions, utils
from kypo.sandbox_ansible_app.models import NetworkingAnsibleCleanupStage,\
    UserAnsibleCleanupStage

from kypo.sandbox_instance_app.lib import sandboxes
from kypo.sandbox_instance_app.lib.stage_handlers import StackStageHandler, AnsibleStageHandler
from kypo.sandbox_instance_app.models import CleanupRequest, SandboxAllocationUnit, \
    StackCleanupStage, AllocationRequest, CleanupRQJob
from kypo.sandbox_instance_app.lib.sandbox_creator import OPENSTACK_QUEUE, ANSIBLE_QUEUE

LOG = structlog.get_logger()


def create_cleanup_request(allocation_unit: SandboxAllocationUnit) -> CleanupRequest:
    """Create cleanup request and enqueue it. Immediately delete sandbox from database."""
    try:
        sandbox = allocation_unit.sandbox
    except ObjectDoesNotExist:
        sandbox = None
    else:
        if hasattr(sandbox, 'lock'):
            raise exceptions.ValidationError('Sandbox ID={} is locked. Unlock it first.'
                                             .format(sandbox.id))

    if not allocation_unit.allocation_request.is_finished:
        raise exceptions.ValidationError(
            f'Create sandbox allocation request ID={allocation_unit.allocation_request.id}'
            f' has not finished yet. You need to cancel it first.'
        )

    if hasattr(allocation_unit, 'cleanup_request'):
        raise exceptions.ValidationError(
            f'Allocation unit ID={allocation_unit.id} already has a cleanup request '
            f'ID={allocation_unit.cleanup_request.id}. Delete it first.')

    request = CleanupRequest.objects.create(allocation_unit=allocation_unit)
    LOG.info('CleanupRequest created', cleanup_request=request,
             allocation_unit=allocation_unit, sandbox=sandbox)

    if sandbox:
        sandbox.delete()
        sandboxes.clear_cache(sandbox)

    enqueue_cleanup_request(request, allocation_unit)
    return request


def create_cleanup_requests(allocation_units: List[SandboxAllocationUnit]) -> List[CleanupRequest]:
    """Batch version of create_cleanup_request."""
    return [create_cleanup_request(unit) for unit in allocation_units]


def delete_cleanup_request(request: CleanupRequest) -> None:
    """Delete given cleanup request."""
    if not request.is_finished:
        raise exceptions.ValidationError('The cleanup request is not finished. '
                                         'You need to cancel it first.')
    request.delete()


def enqueue_cleanup_request(request: CleanupRequest,
                            allocation_unit: SandboxAllocationUnit) -> None:
    """Enqueue given request."""
    stage_user_ans = UserAnsibleCleanupStage.objects.create(
        cleanup_request=request,
        cleanup_request_fk_many=request,
    )
    queue_ansible = django_rq.get_queue(ANSIBLE_QUEUE)
    job_user_ans = queue_ansible.enqueue(
        AnsibleStageHandler().cleanup, stage_name='Cleanup User Ansible',
        stage=stage_user_ans)
    CleanupRQJob.objects.create(cleanup_stage=stage_user_ans, job_id=job_user_ans.id)

    stage_networking = NetworkingAnsibleCleanupStage.objects.create(
        cleanup_request=request,
        cleanup_request_fk_many=request,
    )
    job_networking = queue_ansible.enqueue(
        AnsibleStageHandler().cleanup, stage_name='Cleanup Networking Ansible',
        stage=stage_networking, depends_on=job_user_ans)
    CleanupRQJob.objects.create(cleanup_stage=stage_networking, job_id=job_networking.id)

    stage_stack = StackCleanupStage.objects.create(
        cleanup_request=request,
        cleanup_request_fk_many=request,
    )
    queue_stack = django_rq.get_queue(OPENSTACK_QUEUE,
                                      default_timeout=settings.KYPO_CONFIG.sandbox_delete_timeout)
    job_stack = queue_stack.enqueue(
        StackStageHandler().cleanup, stage_name=stage_stack.__class__.__name__,
        stage=stage_stack,
        depends_on=job_networking)
    CleanupRQJob.objects.create(cleanup_stage=stage_stack, job_id=stage_stack.id)

    queue_default = django_rq.get_queue()
    queue_default.enqueue(delete_allocation_unit, allocation_unit=allocation_unit,
                          depends_on=job_stack)


def delete_allocation_unit(allocation_unit: SandboxAllocationUnit) -> None:
    allocation_unit.delete()
    LOG.info('Allocation Unit deleted from DB', allocation_unit=allocation_unit)


def cancel_allocation_request(alloc_req: AllocationRequest):
    """(Soft) cancel all stages of the Allocation Request."""
    if alloc_req.is_finished:
        raise exceptions.ValidationError(
            f'Allocation request ID {alloc_req.id} is finished and does not need cancelling.'
        )
    AnsibleStageHandler().cancel_allocation(alloc_req.useransibleallocationstage)
    AnsibleStageHandler().cancel_allocation(alloc_req.networkingansibleallocationstage)
    StackStageHandler().cancel_allocation(alloc_req.stackallocationstage)


def cancel_cleanup_request(cleanup_req: CleanupRequest):
    """(Soft) cancel all stages of the Cleanup Request."""
    if cleanup_req.is_finished:
        raise exceptions.ValidationError(
            f'Cleanup request ID {cleanup_req.id} is finished and does not need cancelling.'
        )
    StackStageHandler().cancel_cleanup(cleanup_req.stackcleanupstage)
    AnsibleStageHandler().cancel_cleanup(cleanup_req.networkingansiblecleanupstage)
    AnsibleStageHandler().cancel_cleanup(cleanup_req.useransiblecleanupstage)


def delete_stack(allocation_unit: SandboxAllocationUnit):
    client = utils.get_ostack_client()

    try:
        stack_name = allocation_unit.get_stack_name()
        action, status = client.get_stack_status(stack_name)

        if action == 'DELETE' or action == 'ROLLBACK':
            LOG.warning(f"Sandbox of allocation unit ID={allocation_unit.id} is already being deleted.")
            return

        client.delete_stack(stack_name)
    except Exception as exc:
        raise exceptions.StackError(f'Deleting sandbox of allocation unit ID={allocation_unit.id} failed.'
                                    f' {exc}')
