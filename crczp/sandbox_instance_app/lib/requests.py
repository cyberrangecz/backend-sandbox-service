"""Business logic for creating and managing sandbox allocation and cleanup requests."""

import enum
from collections.abc import Iterable
from functools import partial
from typing import Any

import structlog
from django.contrib.auth.models import User
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction

from crczp.sandbox_common_lib import exceptions
from crczp.sandbox_instance_app.lib import netbird, request_handlers, sandboxes
from crczp.sandbox_instance_app.models import (
    AllocationRequest,
    CleanupRequest,
    Pool,
    SandboxAllocationUnit,
)

LOG = structlog.get_logger()


class StageState(enum.Enum):
    """Enumeration of possible states for a sandbox request stage."""

    IN_QUEUE = 'IN_QUEUE'
    RUNNING = 'RUNNING'
    FINISHED = 'FINISHED'
    FAILED = 'FAILED'


def restart_allocation_stages(unit: SandboxAllocationUnit) -> SandboxAllocationUnit:
    """Restarts failed allocation stages and recreates the existing sandbox and request in the
    database.
    """

    request_handlers.AllocationRequestHandler().restart_request(unit)
    return unit


def create_allocations_requests(
    pool: Pool, count: int, created_by: User | None
) -> list[SandboxAllocationUnit]:
    """Batch version of create_allocation_request. Create count Sandbox Requests."""

    with transaction.atomic():
        units = []
        for _ in range(count):
            unit = SandboxAllocationUnit.objects.create(pool=pool, created_by=created_by)
            # Create the AllocationRequest row synchronously, in the request thread,
            # so the allocation-units listing never returns a freshly created unit
            # with allocation_request=null (the frontend renders that null as
            # "Unknown error / Unknown stage In Queue"). The expensive work — SSH
            # keygen, Sandbox creation and stage enqueuing — still happens later on
            # the default worker via enqueue_request. Until the worker creates the
            # stage rows, get_allocation_request_stages_state reports all stages as
            # IN_QUEUE, which is the correct state for a just-queued request.
            AllocationRequest.objects.create(allocation_unit=unit)
            units.append(unit)

        transaction.on_commit(
            partial(request_handlers.AllocationRequestHandler().enqueue_request, units, created_by)
        )

    return units


def cancel_allocation_request(alloc_req: AllocationRequest) -> None:
    """(Soft) cancel all stages of the Allocation Request."""
    request_handlers.AllocationRequestHandler().cancel_request(alloc_req)


def create_cleanup_request_force(allocation_unit: SandboxAllocationUnit, delete_pool: bool) -> None:
    """Create cleanup request and enqueue it. Immediately delete sandbox from database.
    The force parameter forces the deletion."""
    if (
        hasattr(allocation_unit, 'cleanup_request')
        and not allocation_unit.cleanup_request.is_finished
    ):
        return

    try:
        sandbox = allocation_unit.sandbox
    except ObjectDoesNotExist:
        sandbox = None
    else:
        if sandbox is not None and hasattr(sandbox, 'lock'):
            sandbox.lock.delete()

    if (
        not (
            allocation_unit.allocation_request.stackallocationstage.finished
            or allocation_unit.allocation_request.stackallocationstage.failed
        )
        and allocation_unit.allocation_request.stackallocationstage.start is not None
    ):
        raise exceptions.ValidationError(
            'Cleanup while the first stage is running is not allowed. '
            'Retry once the first stage is finished or fails.'
        )

    if not allocation_unit.allocation_request.is_finished:
        cancel_allocation_request(allocation_unit.allocation_request)

    if sandbox:
        sandboxes.clear_cache(sandbox)
        netbird.destroy_netbird_for_sandbox(sandbox)
        sandbox.delete()

    request_handlers.CleanupRequestHandler(delete_pool=delete_pool).enqueue_request(allocation_unit)


def create_cleanup_request(allocation_unit: SandboxAllocationUnit) -> None:
    """Create cleanup request and enqueue it. Immediately delete sandbox from database."""
    try:
        sandbox = allocation_unit.sandbox
    except ObjectDoesNotExist:
        sandbox = None
    else:
        assert sandbox is not None
        if hasattr(sandbox, 'lock'):
            raise exceptions.ValidationError(f'Sandbox ID={sandbox.id} is locked. Unlock it first.')

    if (
        not (
            allocation_unit.allocation_request.stackallocationstage.finished
            or allocation_unit.allocation_request.stackallocationstage.failed
        )
        and allocation_unit.allocation_request.stackallocationstage.start is not None
    ):
        raise exceptions.ValidationError(
            'Cleanup while the first stage is running is not allowed. '
            'Retry once the first stage is finished or fails.'
        )

    if not allocation_unit.allocation_request.is_finished:
        raise exceptions.ValidationError(
            f'Create sandbox allocation request ID={allocation_unit.allocation_request.id}'
            f' has not finished yet. You need to cancel it first.'
        )

    if hasattr(allocation_unit, 'cleanup_request'):
        raise exceptions.ValidationError(
            f'Allocation unit ID={allocation_unit.id} already has a cleanup request '
            f'ID={allocation_unit.cleanup_request.id}. Delete it first.'
        )

    if sandbox:
        sandboxes.clear_cache(sandbox)
        netbird.destroy_netbird_for_sandbox(sandbox)
        sandbox.delete()

    request_handlers.CleanupRequestHandler().enqueue_request(allocation_unit)


def create_cleanup_requests(
    allocation_units: Iterable[SandboxAllocationUnit],
    force: bool = False,
    delete_pool: bool = False,
) -> None:
    """Batch version of create_cleanup_request."""
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
        raise exceptions.ValidationError(
            'The cleanup request is not finished. You need to cancel it first.'
        )
    request.delete()


def get_allocation_request_stages_state(request: AllocationRequest) -> list[str]:
    """Get AllocationRequests stages state."""
    try:
        stages = [
            request.stackallocationstage,
            request.networkingansibleallocationstage,
            request.useransibleallocationstage,
        ]
    except ObjectDoesNotExist:
        return [StageState.IN_QUEUE.value, StageState.IN_QUEUE.value, StageState.IN_QUEUE.value]

    return _get_request_stages_state(stages)


def get_cleanup_request_stages_state(request: CleanupRequest) -> list[str]:
    """Get CleanupRequests stages state."""
    try:
        stages = [
            request.stackcleanupstage,
            request.networkingansiblecleanupstage,
            request.useransiblecleanupstage,
        ]
    except ObjectDoesNotExist:
        return [StageState.IN_QUEUE.value, StageState.IN_QUEUE.value, StageState.IN_QUEUE.value]

    return _get_request_stages_state(stages)


def _get_request_stages_state(stages: list[Any]) -> list[str]:
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
