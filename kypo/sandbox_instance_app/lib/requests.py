import enum
from typing import List, Optional
import structlog
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.contrib.auth.models import User

from kypo.sandbox_common_lib import exceptions, utils

from kypo.sandbox_instance_app.models import Pool, Sandbox, SandboxAllocationUnit,\
    AllocationRequest, CleanupRequest, SandboxLock
from kypo.sandbox_instance_app.lib import request_handlers, sandboxes

LOG = structlog.get_logger()


class StageState(enum.Enum):
    IN_QUEUE = "IN_QUEUE"
    RUNNING = "RUNNING"
    FINISHED = "FINISHED"
    FAILED = "FAILED"


def create_allocation_request(pool: Pool, created_by: Optional[User]) -> SandboxAllocationUnit:
    """Create Sandbox Allocation Request.
    Also create sandbox, but do not save it to the database until
    successfully created.
    """
    unit = SandboxAllocationUnit.objects.create(pool=pool, created_by=created_by)
    request = AllocationRequest.objects.create(allocation_unit=unit)
    pri_key, pub_key = utils.generate_ssh_keypair()
    sandbox = Sandbox(id=sandboxes.generate_new_sandbox_uuid(), allocation_unit=unit,
                      private_user_key=pri_key, public_user_key=pub_key)
    request_handlers.AllocationRequestHandler(request).enqueue_request(sandbox)
    return unit


def restart_allocation_stages(unit: SandboxAllocationUnit) -> SandboxAllocationUnit:
    """Restarts failed allocation stages and recreates the existing sandbox and request in the
     database.
    """
    request = unit.allocation_request
    pri_key, pub_key = utils.generate_ssh_keypair()
    sandbox = Sandbox(id=sandboxes.generate_new_sandbox_uuid(), allocation_unit=unit,
                      private_user_key=pri_key, public_user_key=pub_key)
    request_handlers.AllocationRequestHandler(request).enqueue_request(sandbox, restart_stages=True)
    return unit


def create_allocations_requests(pool: Pool, count: int, created_by: Optional[User])\
        -> List[SandboxAllocationUnit]:
    """Batch version of create_allocation_request. Create count Sandbox Requests."""
    return [create_allocation_request(pool, created_by) for _ in range(count)]


def cancel_allocation_request(alloc_req: AllocationRequest):
    """(Soft) cancel all stages of the Allocation Request."""
    request_handlers.AllocationRequestHandler(alloc_req).cancel_request()


def create_cleanup_request(allocation_unit: SandboxAllocationUnit,
                           force: bool = False) -> CleanupRequest:
    """Create cleanup request and enqueue it. Immediately delete sandbox from database.
    The force parameter forces the deletion."""
    try:
        sandbox = allocation_unit.sandbox
    except ObjectDoesNotExist:
        sandbox = None
    else:
        if hasattr(sandbox, 'lock'):
            if force:
                SandboxLock.objects.get(sandbox=sandbox).delete()
            else:
                raise exceptions.ValidationError('Sandbox ID={} is locked. Unlock it first.'
                                                 .format(sandbox.id))

    if not (allocation_unit.allocation_request.stackallocationstage.finished or
            allocation_unit.allocation_request.stackallocationstage.failed) and \
            allocation_unit.allocation_request.stackallocationstage.start is not None:
        raise exceptions.ValidationError('Cleanup while the first stage is running is not allowed. '
                                         'Retry once the first stage is finished or fails.')

    if not allocation_unit.allocation_request.is_finished:
        if force:
            cancel_allocation_request(allocation_unit.allocation_request)
        else:
            raise exceptions.ValidationError(
                f'Create sandbox allocation request ID={allocation_unit.allocation_request.id}'
                f' has not finished yet. You need to cancel it first.'
            )

    if hasattr(allocation_unit, 'cleanup_request'):
        if force:
            if not allocation_unit.cleanup_request.is_finished:
                cancel_cleanup_request(allocation_unit.cleanup_request)
            delete_cleanup_request(allocation_unit.cleanup_request)
        else:
            raise exceptions.ValidationError(
                f'Allocation unit ID={allocation_unit.id} already has a cleanup request '
                f'ID={allocation_unit.cleanup_request.id}. Delete it first.')
    request = CleanupRequest.objects.create(allocation_unit=allocation_unit)
    LOG.info('CleanupRequest created', cleanup_request=request,
             allocation_unit=allocation_unit, sandbox=sandbox)

    if sandbox:
        sandbox.delete()
        sandboxes.clear_cache(sandbox)
    request_handlers.CleanupRequestHandler(request).enqueue_request()
    return request


def create_cleanup_requests(allocation_units: List[SandboxAllocationUnit], force: bool = False)\
        -> List[CleanupRequest]:
    """Batch version of create_cleanup_request."""
    with transaction.atomic():
        return [create_cleanup_request(unit, force) for unit in allocation_units]


def cancel_cleanup_request(cleanup_req: CleanupRequest) -> None:
    """(Soft) cancel all stages of the Cleanup Request."""
    request_handlers.CleanupRequestHandler(cleanup_req).cancel_request()


def delete_cleanup_request(request: CleanupRequest) -> None:
    """Delete given cleanup request."""
    if not request.is_finished:
        raise exceptions.ValidationError('The cleanup request is not finished. '
                                         'You need to cancel it first.')
    request.delete()


def get_allocation_request_stages_state(request: AllocationRequest) -> List[str]:
    """Get AllocationRequests stages state."""
    stages = [request.stackallocationstage, request.networkingansibleallocationstage,
              request.useransibleallocationstage]

    return _get_request_stages_state(stages)


def get_cleanup_request_stages_state(request: CleanupRequest) -> List[str]:
    """Get CleanupRequests stages state."""
    stages = [request.stackcleanupstage, request.networkingansiblecleanupstage,
              request.useransiblecleanupstage]

    return _get_request_stages_state(stages)


def _get_request_stages_state(stages) -> List[str]:
    """Get SandboxRequests stages state."""
    stages_state = []

    for stage in stages:
        if stage.end is None and stage.start:
            stages_state.append(StageState.RUNNING.value)
        elif stage.failed:
            stages_state.append(StageState.FAILED.value)
        elif stage.finished:
            stages_state.append(StageState.FINISHED.value)
        else:
            stages_state.append(StageState.IN_QUEUE.value)

    return stages_state
