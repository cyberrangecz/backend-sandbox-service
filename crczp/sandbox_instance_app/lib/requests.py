import enum
from typing import List, Optional

import structlog
from django.contrib.auth.models import User
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from functools import partial

from crczp.sandbox_common_lib import exceptions
from crczp.sandbox_instance_app.lib import request_handlers, sandboxes
from crczp.sandbox_instance_app.models import Pool, SandboxAllocationUnit, \
    AllocationRequest, CleanupRequest

LOG = structlog.get_logger()


class StageState(enum.Enum):
    IN_QUEUE = "IN_QUEUE"
    RUNNING = "RUNNING"
    FINISHED = "FINISHED"
    FAILED = "FAILED"


def restart_allocation_stages(unit: SandboxAllocationUnit) -> SandboxAllocationUnit:
    """Restarts failed allocation stages and recreates the existing sandbox and request in the
     database.
    """

    request_handlers.AllocationRequestHandler().restart_request(unit)
    return unit


def create_allocations_requests(
    pool: Pool,
    count: int,
    created_by: Optional[User],
    created_by_sub: Optional[str] = None,
) -> List[SandboxAllocationUnit]:
    """Batch version of create_allocation_request. Create count Sandbox Requests.
    When called from training-service (service-to-service), created_by_sub is the
    trainee's OIDC sub; created_by may be None.
    """

    with transaction.atomic():
        units = [
            SandboxAllocationUnit.objects.create(
                pool=pool,
                created_by=created_by,
                created_by_sub=created_by_sub,
            )
            for _ in range(count)
        ]

        transaction.on_commit(
            partial(request_handlers.AllocationRequestHandler().enqueue_request, units, created_by)
        )

    return units


def cancel_allocation_request(alloc_req: AllocationRequest):
    """(Soft) cancel all stages of the Allocation Request."""
    request_handlers.AllocationRequestHandler().cancel_request(alloc_req)


def can_force_cleanup_unit(unit: SandboxAllocationUnit) -> bool:
    """
    Return True if this unit can be force-cleaned without hitting "first stage is running" block.
    Used by batch cleanup (Delete All / Delete Unlocked) to skip ineligible units and process the rest.
    """
    if hasattr(unit, 'cleanup_request') and unit.cleanup_request is not None and not unit.cleanup_request.is_finished:
        return False
    try:
        stack = unit.allocation_request.stackallocationstage
    except (ObjectDoesNotExist, AttributeError):
        return True
    if stack.start is None:
        return True
    if getattr(stack, 'finished', False) or getattr(stack, 'failed', False):
        return True
    return False


def create_cleanup_request_force(allocation_unit: SandboxAllocationUnit, delete_pool):
    """Create cleanup request and enqueue it. Immediately delete sandbox from database.
    The force parameter forces the deletion."""
    if hasattr(allocation_unit, 'cleanup_request') and not allocation_unit.cleanup_request.is_finished:
        return

    try:
        sandbox = allocation_unit.sandbox
    except ObjectDoesNotExist:
        sandbox = None
    else:
        if hasattr(sandbox, 'lock'):
            sandbox.lock.delete()

    if not (allocation_unit.allocation_request.stackallocationstage.finished or
            allocation_unit.allocation_request.stackallocationstage.failed) and \
            allocation_unit.allocation_request.stackallocationstage.start is not None:
        raise exceptions.ValidationError('Cleanup while the first stage is running is not allowed. '
                                         'Retry once the first stage is finished or fails.')

    if not allocation_unit.allocation_request.is_finished:
        cancel_allocation_request(allocation_unit.allocation_request)

    if sandbox:
        sandboxes.clear_cache(sandbox)
        sandbox.delete()

    request_handlers.CleanupRequestHandler(delete_pool=delete_pool).enqueue_request(allocation_unit)


def create_cleanup_request(allocation_unit: SandboxAllocationUnit):
    """Create cleanup request and enqueue it. Immediately delete sandbox from database."""
    try:
        sandbox = allocation_unit.sandbox
    except ObjectDoesNotExist:
        sandbox = None
    else:
        if hasattr(sandbox, 'lock'):
            raise exceptions.ValidationError('Sandbox ID={} is locked. Unlock it first.'
                                             .format(sandbox.id))

    if not (allocation_unit.allocation_request.stackallocationstage.finished or
            allocation_unit.allocation_request.stackallocationstage.failed) and \
            allocation_unit.allocation_request.stackallocationstage.start is not None:
        raise exceptions.ValidationError('Cleanup while the first stage is running is not allowed. '
                                         'Retry once the first stage is finished or fails.')

    if not allocation_unit.allocation_request.is_finished:
        raise exceptions.ValidationError(
            f'Create sandbox allocation request ID={allocation_unit.allocation_request.id}'
            f' has not finished yet. You need to cancel it first.'
        )

    if hasattr(allocation_unit, 'cleanup_request'):
        raise exceptions.ValidationError(
            f'Allocation unit ID={allocation_unit.id} already has a cleanup request '
            f'ID={allocation_unit.cleanup_request.id}. Delete it first.')

    if sandbox:
        sandboxes.clear_cache(sandbox)
        sandbox.delete()

    request_handlers.CleanupRequestHandler().enqueue_request(allocation_unit)


def create_cleanup_requests(allocation_units: List[SandboxAllocationUnit], force: bool = False,
                            delete_pool: bool = False):
    """Batch version of create_cleanup_request.
    When force=True, skips units that cannot be force-cleaned (e.g. first stage still running)
    and creates cleanup only for eligible units, so Delete All / Delete Unlocked never fail
    the whole batch because of one ineligible sandbox.
    """
    if force:
        allocation_units = [u for u in allocation_units if can_force_cleanup_unit(u)]
    for unit in allocation_units:
        if force:
            create_cleanup_request_force(unit, delete_pool)
        else:
            create_cleanup_request(unit)


def cancel_cleanup_request(cleanup_req: CleanupRequest) -> None:
    """(Soft) cancel all stages of the Cleanup Request."""
    request_handlers.CleanupRequestHandler().cancel_request(cleanup_req)


def delete_cleanup_request(request: CleanupRequest) -> None:
    """Delete given cleanup request."""
    if not request.is_finished:
        raise exceptions.ValidationError('The cleanup request is not finished. '
                                         'You need to cancel it first.')
    request.delete()


def get_allocation_request_stages_state(request: AllocationRequest) -> List[str]:
    """Get AllocationRequests stages state."""
    try:
        stages = [request.stackallocationstage, request.networkingansibleallocationstage,
                  request.useransibleallocationstage]
    except ObjectDoesNotExist:
        return [StageState.IN_QUEUE.value, StageState.IN_QUEUE.value, StageState.IN_QUEUE.value]

    return _get_request_stages_state(stages)


def get_cleanup_request_stages_state(request: CleanupRequest) -> List[str]:
    """Get CleanupRequests stages state."""
    try:
        stages = [request.stackcleanupstage, request.networkingansiblecleanupstage,
                  request.useransiblecleanupstage]
    except ObjectDoesNotExist:
        return [StageState.IN_QUEUE.value, StageState.IN_QUEUE.value, StageState.IN_QUEUE.value]

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


def is_allocation_fully_in_queue(unit: SandboxAllocationUnit) -> bool:
    """
    Return True if the allocation unit's allocation request has not started yet
    (all stages IN_QUEUE). Such units can be cancelled without going through cleanup.
    """
    try:
        alloc = getattr(unit, 'allocation_request', None)
        if alloc is None:
            return False
        stack_stage = getattr(alloc, 'stackallocationstage', None)
        if stack_stage is None:
            return False
        return stack_stage.start is None
    except ObjectDoesNotExist:
        return False


def is_allocation_first_stage_running(unit: SandboxAllocationUnit) -> bool:
    """
    Return True if the allocation unit's first (stack) stage has started but is not
    finished or failed. Such units are "stuck" and can be force-cancelled to remove
    them from the Cyber Range DB (OpenStack must be cleaned up manually).
    """
    if hasattr(unit, 'cleanup_request') and unit.cleanup_request is not None:
        return False
    try:
        stack = unit.allocation_request.stackallocationstage
    except (ObjectDoesNotExist, AttributeError):
        return False
    if stack.start is None:
        return False
    if getattr(stack, 'finished', False) or getattr(stack, 'failed', False):
        return False
    return True


def cancel_queued_allocation_units_in_pool(pool_id: int) -> int:
    """
    Cancel all allocation units in the pool that are fully IN_QUEUE (no stage started).
    Sandbox is created at enqueue time (before any stage runs), so we must delete it first
    when cancelling. For each such unit: cancel allocation request, delete sandbox if any,
    delete unit, decrement pool.size.
    Returns the number of units cancelled.
    """
    from crczp.sandbox_instance_app.lib import pools
    pools.get_pool(pool_id)
    units = SandboxAllocationUnit.objects.filter(pool_id=pool_id).select_related(
        'allocation_request', 'allocation_request__stackallocationstage', 'cleanup_request'
    )
    queued_units = [
        u for u in units
        if is_allocation_fully_in_queue(u)
        and not (hasattr(u, 'cleanup_request') and u.cleanup_request is not None)
    ]

    if not queued_units:
        return 0

    cancelled = 0
    with transaction.atomic():
        pool = Pool.objects.select_for_update().get(pk=pool_id)
        for unit in queued_units:
            unit = SandboxAllocationUnit.objects.select_related(
                'cleanup_request', 'allocation_request', 'allocation_request__stackallocationstage'
            ).filter(pk=unit.pk).first()
            if not unit or getattr(unit, 'cleanup_request', None) is not None:
                continue
            if not is_allocation_fully_in_queue(unit):
                continue
            try:
                cancel_allocation_request(unit.allocation_request)
            except exceptions.ValidationError:
                pass
            try:
                sandbox = unit.sandbox
            except ObjectDoesNotExist:
                sandbox = None
            else:
                if hasattr(sandbox, 'lock'):
                    sandbox.lock.delete()
                sandboxes.clear_cache(sandbox)
                sandbox.delete()
            unit.delete()
            pool.size -= 1
            cancelled += 1
        pool.save()
    return cancelled


def force_cancel_allocation_units_in_pool(pool_id: int) -> int:
    """
    Force-cancel all allocation units in the pool whose first (stack) stage has
    started but is not finished/failed — "stuck" allocations. Removes them from
    the Cyber Range DB only; OpenStack (or other external) resources must be
    cleaned up manually. For each such unit: cancel allocation request (RQ jobs),
    remove lock if any, delete sandbox record, delete allocation unit, decrement
    pool.size. Does not create a cleanup request. Returns the number of units
    force-cancelled.
    """
    from crczp.sandbox_instance_app.lib import pools
    pools.get_pool(pool_id)
    units = SandboxAllocationUnit.objects.filter(pool_id=pool_id).select_related(
        'allocation_request', 'allocation_request__stackallocationstage', 'cleanup_request'
    )
    stuck_units = [
        u for u in units
        if is_allocation_first_stage_running(u)
    ]

    if not stuck_units:
        return 0

    cancelled = 0
    with transaction.atomic():
        pool = Pool.objects.select_for_update().get(pk=pool_id)
        for u in stuck_units:
            unit = SandboxAllocationUnit.objects.select_related(
                'cleanup_request', 'allocation_request', 'allocation_request__stackallocationstage'
            ).filter(pk=u.pk).first()
            if not unit or not is_allocation_first_stage_running(unit):
                continue
            try:
                cancel_allocation_request(unit.allocation_request)
            except exceptions.ValidationError:
                pass
            try:
                sandbox = unit.sandbox
            except ObjectDoesNotExist:
                sandbox = None
            else:
                if hasattr(sandbox, 'lock'):
                    sandbox.lock.delete()
                sandboxes.clear_cache(sandbox)
                sandbox.delete()
            unit.delete()
            pool.size -= 1
            cancelled += 1
        pool.save()
    return cancelled


def force_cleanup_units_in_pool(pool_id: int) -> int:
    """
    Force-remove all allocation units in the pool that have a cleanup request which is
    not finished (cleanup running or stuck). Cancels the cleanup RQ jobs, deletes sandbox
    record if any, deletes the allocation unit (cascade deletes cleanup request), and
    decrements pool.size. Use when cleanup is stuck (e.g. at jump proxy stage).
    Returns the number of units force-cleaned.
    """
    from crczp.sandbox_instance_app.lib import pools
    pools.get_pool(pool_id)
    units = SandboxAllocationUnit.objects.filter(pool_id=pool_id).select_related(
        'cleanup_request'
    )
    stuck_cleanup_units = [
        u for u in units
        if getattr(u, 'cleanup_request', None) is not None
        and not u.cleanup_request.is_finished
    ]

    if not stuck_cleanup_units:
        return 0

    cleaned = 0
    with transaction.atomic():
        pool = Pool.objects.select_for_update().get(pk=pool_id)
        for u in stuck_cleanup_units:
            unit = SandboxAllocationUnit.objects.select_related('cleanup_request').filter(
                pk=u.pk
            ).first()
            if not unit or getattr(unit, 'cleanup_request', None) is None or unit.cleanup_request.is_finished:
                continue
            try:
                cancel_cleanup_request(unit.cleanup_request)
            except exceptions.ValidationError:
                pass
            try:
                sandbox = unit.sandbox
            except ObjectDoesNotExist:
                sandbox = None
            else:
                if hasattr(sandbox, 'lock'):
                    sandbox.lock.delete()
                sandboxes.clear_cache(sandbox)
                sandbox.delete()
            unit.delete()
            pool.size -= 1
            cleaned += 1
        pool.save()
    return cleaned
