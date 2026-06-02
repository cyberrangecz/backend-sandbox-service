"""Handlers for sandbox allocation and cleanup request lifecycle management."""

import abc
from collections.abc import Callable
from functools import partial
from typing import Any, override

import django_rq
import structlog
from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction
from rq import Queue
from rq.job import Job

from crczp.sandbox_ansible_app.models import (
    AnsibleAllocationStage,
    NetworkingAnsibleAllocationStage,
    NetworkingAnsibleCleanupStage,
    UserAnsibleAllocationStage,
    UserAnsibleCleanupStage,
)
from crczp.sandbox_common_lib import exceptions, utils
from crczp.sandbox_instance_app.lib import pools, requests, sandboxes
from crczp.sandbox_instance_app.lib.stage_handlers import (
    AllocationAnsibleStageHandler,
    AllocationStackStageHandler,
    AnsibleStageHandler,
    CleanupAnsibleStageHandler,
    CleanupStackStageHandler,
    StackStageHandler,
    StageHandler,
)
from crczp.sandbox_instance_app.models import (
    AllocationRequest,
    AllocationRQJob,
    CleanupRequest,
    CleanupRQJob,
    CleanupStage,
    Pool,
    Sandbox,
    SandboxAllocationUnit,
    SandboxRequest,
    SandboxRequestGroup,
    StackAllocationStage,
    StackCleanupStage,
)

LOG = structlog.get_logger()

OPENSTACK_QUEUE = 'openstack'
ANSIBLE_QUEUE = 'ansible'
AllocationStage = StackAllocationStage | AnsibleAllocationStage


class RequestHandler(abc.ABC):
    """
    Handles DB SandboxRequest object and generalizes its common tasks.
    """

    queue_default: Queue = django_rq.get_queue()
    queue_stack: Queue = django_rq.get_queue(
        OPENSTACK_QUEUE, default_timeout=settings.CRCZP_CONFIG.sandbox_build_timeout
    )
    queue_ansible: Queue = django_rq.get_queue(
        ANSIBLE_QUEUE, default_timeout=settings.CRCZP_CONFIG.sandbox_ansible_timeout
    )
    request: SandboxRequest | None = None

    @abc.abstractmethod
    def enqueue_request(self, *args: Any, **kwargs: Any) -> None:
        """
        Handles request stages creation and their enqueuing.
        """

    def cancel_request(self, request: SandboxRequest) -> None:
        """
        (Soft) cancel of all request stages.
        """
        self.request = request
        if hasattr(self.request, 'is_finished') and self.request.is_finished:
            msg = (
                f'Request {self.request.__class__.__name__} with ID {self.request.id}'
                f' is finished and does not need cancelling.'
            )
            raise exceptions.ValidationError(msg)
        for stage_handler in self._get_stage_handlers():
            stage_handler.cancel()

    @abc.abstractmethod
    def _create_stage_handlers(self, *args: Any, **kwargs: Any) -> list[StageHandler]:
        """
        Create a new DB stages for this request and return their handlers.
        """

    @abc.abstractmethod
    def _get_stage_handlers(self) -> list[StageHandler]:
        """
        Get handlers of existing DB stages for this request.
        """

    def _enqueue_request(
        self, stage_handlers: list[StageHandler], finalizing_stage: Callable[[], None]
    ) -> None:
        """
        Enqueue methods of the given stage handlers.

        The order of stage handlers is important.
          Every subsequent stage depends on the previous one, and it is enqueued as such.
        """
        previous_job = None
        for stage_handler in stage_handlers:
            if isinstance(stage_handler, StackStageHandler):
                queue = self.queue_stack
            elif isinstance(stage_handler, AnsibleStageHandler):
                queue = self.queue_ansible
            else:
                queue = self.queue_default
            previous_job = queue.enqueue(stage_handler.execute, depends_on=previous_job)
            stage_handler.set_job_id(previous_job.id)

        self.queue_default.enqueue(finalizing_stage, depends_on=previous_job)

    @staticmethod
    def _get_finalizing_stage_function(
        func: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> Callable[[], None]:
        """
        Practically just wraps the class functools.partial
          and solves its missing attribute __module__.
        """
        # Class partial does not copy attribute __module__ from inner function
        #   which is required by Queue.enqueue method.
        # This is a known bug since September 2018.
        finalizing_stage_function = partial(func, *args, **kwargs)
        finalizing_stage_function.__name__ = (  # type: ignore[attr-defined]
            'finalizing_stage_function'
        )
        finalizing_stage_function.__module__ = func.__module__
        return finalizing_stage_function

    @staticmethod
    def create_request_group(units: list[SandboxAllocationUnit]) -> SandboxRequestGroup:
        """Create a SandboxRequestGroup for tracking batch allocation progress."""
        email = units[0].created_by.email if units[0].created_by else ''
        group = SandboxRequestGroup.objects.create(
            pool=units[0].pool, unit_count=len(units), email=email
        )
        group.save()
        return group


class AllocationRequestHandler(RequestHandler):
    """
    Specifies allocation request stages and tasks for their manipulation.
    """

    request: AllocationRequest

    @transaction.atomic
    def _enqueue_stages(self, sandbox: Sandbox, stage_handlers: list[StageHandler]) -> None:
        """
        Handles request stages creation (or restart) and their enqueuing.
        """
        finalizing_stage_function = self._get_finalizing_stage_function(
            self._mark_sandbox_as_ready, sandbox
        )
        on_commit_method = partial(self._enqueue_request, stage_handlers, finalizing_stage_function)

        transaction.on_commit(on_commit_method)

    def _create_allocation_jobs(
        self, units: list[SandboxAllocationUnit], created_by: User | None
    ) -> None:
        """Create allocation requests and enqueue stage jobs for each unit."""
        if units[0].pool.send_emails and created_by is not None and created_by.email:
            allocation_group = self.create_request_group(units)
        else:
            allocation_group = None

        for unit in units:
            LOG.info('Creating sandbox for allocation unit: %s', unit.id)
            self.request = AllocationRequest.objects.create(allocation_unit=unit)
            pri_key, pub_key = utils.generate_ssh_keypair()
            sandbox = Sandbox(
                id=sandboxes.generate_new_sandbox_uuid(),
                allocation_unit=unit,
                private_user_key=pri_key,
                public_user_key=pub_key,
            )
            sandbox.save()
            stage_handlers = self._create_stage_handlers(sandbox, allocation_group)
            self._enqueue_stages(sandbox, stage_handlers)

    @override
    def enqueue_request(  # pylint: disable=arguments-differ
        self, units: list[SandboxAllocationUnit], created_by: User | None
    ) -> None:
        """Enqueue the allocation request creation job for the given units."""
        self.queue_default.enqueue(self._create_allocation_jobs, units, created_by)

    def _create_restart_jobs(self, unit: SandboxAllocationUnit) -> None:
        LOG.info('Restarting sandbox allocation unit: %s', unit.id)
        self.request = unit.allocation_request
        Sandbox.objects.get(allocation_unit=unit).delete()
        pri_key, pub_key = utils.generate_ssh_keypair()
        sandbox = Sandbox(
            id=sandboxes.generate_new_sandbox_uuid(),
            allocation_unit=unit,
            private_user_key=pri_key,
            public_user_key=pub_key,
        )
        sandbox.save()
        stage_handlers = self._restart_stage_handlers(sandbox)
        self._enqueue_stages(sandbox, stage_handlers)

    def restart_request(self, unit: SandboxAllocationUnit) -> None:
        """Enqueue a restart job for the given allocation unit."""
        self.queue_default.enqueue(self._create_restart_jobs, unit)

    def _create_db_stage(
        self, stage_class: type[AllocationStage], *args: Any, **kwargs: Any
    ) -> AllocationStage:
        """
        Simplifies stage creation in database.
        """
        return stage_class.objects.create(  # type: ignore[misc]
            *args,
            allocation_request=self.request,
            allocation_request_fk_many=self.request,
            **kwargs,
        )

    @override
    def _create_stage_handlers(  # pylint: disable=arguments-differ
        self, sandbox: Sandbox, group: SandboxRequestGroup | None
    ) -> list[StageHandler]:
        """
        Create a new DB stages for this request and return their handlers.
        """
        stack_stage = self._create_db_stage(StackAllocationStage)
        stack_stage_handler = AllocationStackStageHandler(stack_stage, request_group=group)

        networking_stage = self._create_db_stage(
            NetworkingAnsibleAllocationStage,
            repo_url=settings.CRCZP_CONFIG.ansible_networking_url,
            rev=settings.CRCZP_CONFIG.ansible_networking_rev,
        )
        networking_stage_handler = AllocationAnsibleStageHandler(
            networking_stage,  # type: ignore[arg-type]
            sandbox,
            request_group=group,
        )

        user_stage = self._create_db_stage(
            UserAnsibleAllocationStage,
            repo_url=self.request.allocation_unit.pool.definition.url,
            rev=self.request.allocation_unit.pool.rev_sha,
        )
        user_stage_handler = AllocationAnsibleStageHandler(
            user_stage,  # type: ignore[arg-type]
            sandbox,
            request_group=group,
        )

        return [stack_stage_handler, networking_stage_handler, user_stage_handler]

    def _restart_stage_handlers(self, sandbox: Sandbox) -> list[StageHandler]:
        """
        Restart failed DB stages for this request and return their handlers.
        """

        if not self.request.is_finished:
            raise exceptions.ValidationError('Allocation of the sandbox is still in progress.')
        if not self.request.useransibleallocationstage.failed:
            raise exceptions.ValidationError(
                'All stages finished without failing. Only failed stages can be restarted.'
            )

        stage_handlers: list[StageHandler] = []
        if self.request.stackallocationstage.failed:
            self.request.stackallocationstage.delete()
            stack_stage = self._create_db_stage(StackAllocationStage)
            stage_handlers.append(AllocationStackStageHandler(stack_stage))

        if (
            self.request.stackallocationstage.failed
            or self.request.networkingansibleallocationstage.failed
        ):
            self.request.networkingansibleallocationstage.delete()
            networking_stage = self._create_db_stage(
                NetworkingAnsibleAllocationStage,
                repo_url=settings.CRCZP_CONFIG.ansible_networking_url,
                rev=settings.CRCZP_CONFIG.ansible_networking_rev,
            )
            stage_handlers.append(
                AllocationAnsibleStageHandler(networking_stage, sandbox)  # type: ignore[arg-type]
            )

        self.request.useransibleallocationstage.delete()
        user_stage = self._create_db_stage(
            UserAnsibleAllocationStage,
            repo_url=self.request.allocation_unit.pool.definition.url,
            rev=self.request.allocation_unit.pool.rev_sha,
        )
        stage_handlers.append(
            AllocationAnsibleStageHandler(user_stage, sandbox)  # type: ignore[arg-type]
        )

        return stage_handlers

    @override
    def _get_stage_handlers(self) -> list[StageHandler]:
        """
        Get handlers of existing DB stages for this request.
        """
        user_handler = AllocationAnsibleStageHandler(self.request.useransibleallocationstage)
        networking_handler = AllocationAnsibleStageHandler(
            self.request.networkingansibleallocationstage
        )
        stack_handler = AllocationStackStageHandler(self.request.stackallocationstage)

        return [user_handler, networking_handler, stack_handler]

    @staticmethod
    def _mark_sandbox_as_ready(sandbox: Sandbox) -> None:
        """
        Named method used as finalizing stage function.

        Sets sandbox.ready to True, meaning it can be used for trainings.
        """
        sandbox.ready = True
        sandbox.save()


class CleanupRequestHandler(RequestHandler):
    """
    Specifies cleanup request stages and tasks for their manipulation.
    """

    request: CleanupRequest
    delete_pool: bool

    def __init__(self, delete_pool: bool = False) -> None:
        self.delete_pool = delete_pool

    @transaction.atomic
    def _enqueue_stages(self) -> None:
        """
        Handles request stages creation and their enqueuing.
        """
        stage_handlers = self._create_stage_handlers()
        finalizing_stage_function = self._get_finalizing_stage_function(
            self._delete_allocation_unit, self.request.allocation_unit, self.request
        )
        on_commit_method = partial(self._enqueue_request, stage_handlers, finalizing_stage_function)

        transaction.on_commit(on_commit_method)

    def _create_cleanup_jobs(self, unit: SandboxAllocationUnit) -> None:
        if hasattr(unit, 'cleanup_request'):
            self.request = unit.cleanup_request
            LOG.info('Reusing cleanup request %s for allocation unit %s', self.request.id, unit.id)
        else:
            self.request = CleanupRequest.objects.create(allocation_unit=unit)
            LOG.info('Created cleanup request %s for allocation unit %s', self.request.id, unit.id)

        self._enqueue_stages()

    @override
    def enqueue_request(self, unit: SandboxAllocationUnit) -> None:  # pylint: disable=arguments-differ
        self.queue_default.enqueue(self._create_cleanup_jobs, unit)

    def _create_db_stage(
        self, stage_class: type[CleanupStage], *args: Any, **kwargs: Any
    ) -> CleanupStage:
        """
        Simplifies stage creation in database.
        """
        return stage_class.objects.create(  # type: ignore[misc]
            *args, cleanup_request=self.request, cleanup_request_fk_many=self.request, **kwargs
        )

    @override
    def _create_stage_handlers(self) -> list[StageHandler]:  # pylint: disable=arguments-differ
        """
        Create a new DB stages for this request and return their handlers.
        """

        if hasattr(self.request, 'useransiblecleanupstage'):
            self.request.useransiblecleanupstage.delete()
        user_stage = self._create_db_stage(UserAnsibleCleanupStage)
        user_stage_handler = CleanupAnsibleStageHandler(user_stage)  # type: ignore[arg-type]

        if hasattr(self.request, 'networkingansiblecleanupstage'):
            self.request.networkingansiblecleanupstage.delete()
        networking_stage = self._create_db_stage(NetworkingAnsibleCleanupStage)
        networking_stage_handler = CleanupAnsibleStageHandler(
            networking_stage  # type: ignore[arg-type]
        )

        if hasattr(self.request, 'stackcleanupstage'):
            self.request.stackcleanupstage.delete()
        stack_stage = self._create_db_stage(StackCleanupStage)
        stack_stage_handler = CleanupStackStageHandler(stack_stage)

        return [user_stage_handler, networking_stage_handler, stack_stage_handler]

    @override
    def _get_stage_handlers(self) -> list[StageHandler]:
        """
        Get handlers of existing DB stages for this request.
        """
        stack_handler = CleanupStackStageHandler(self.request.stackcleanupstage)
        networking_handler = CleanupAnsibleStageHandler(self.request.networkingansiblecleanupstage)
        user_handler = CleanupAnsibleStageHandler(self.request.useransiblecleanupstage)
        return [stack_handler, networking_handler, user_handler]

    def _delete_allocation_unit(
        self, allocation_unit: SandboxAllocationUnit, request: CleanupRequest
    ) -> None:
        """
        Named method used as finalizing stage function.
        """
        with transaction.atomic():  # avoid race condition with decrementing pool size in DB
            pool = Pool.objects.select_for_update().get(id=allocation_unit.pool.id)
            pool.size -= 1
            pool.save()

        allocation_unit.delete()
        LOG.info('Allocation Unit deleted from DB', allocation_unit=allocation_unit)
        requests.delete_cleanup_request(request)
        LOG.info('Cleanup request deleted from DB', cleanup_request=request)
        if pool.size == 0 and self.delete_pool:
            pools.delete_pool(pool)
            LOG.info(
                'Pool deleted from DB by final cleanup finishing',
                cleanup_request=request,
                pool=pool,
            )


def request_exception_handler(job: Job, _exc_type: Any, _exc_value: Any, _traceback: Any) -> None:
    """
    Handle exception raised during request execution in Redis queue worker.

    :param job: The Job that raised an exception.
    :param exc_type: The type of the exception being handled.
    :param exc_value: The exception instance. Instance of exc_value.
    :param traceback: Traceback object which encapsulates the call stack.
    """
    request_handler: RequestHandler | None = None
    request: SandboxRequest | None = None
    try:
        request = AllocationRQJob.objects.get(
            job_id=job.id
        ).allocation_stage.allocation_request_fk_many
        request_handler = AllocationRequestHandler()
    except AllocationRQJob.DoesNotExist:
        try:
            request = CleanupRQJob.objects.get(job_id=job.id).cleanup_stage.cleanup_request_fk_many
            request_handler = CleanupRequestHandler()
        except CleanupRQJob.DoesNotExist:
            pass

    if request_handler and request:
        request_handler.cancel_request(request)
