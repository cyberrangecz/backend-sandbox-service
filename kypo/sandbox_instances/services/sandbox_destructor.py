from typing import Optional
import django_rq
import structlog
from django.utils import timezone
from django.core.exceptions import ObjectDoesNotExist

from ...common import utils, exceptions
from ...common.config import config

from ..models import Sandbox, CleanupRequest, SandboxAllocationUnit, CleanupStage

LOG = structlog.get_logger()


def delete_sandbox_request(allocation_unit: SandboxAllocationUnit) -> CleanupRequest:
    """
    Create delete request and attempt to delete a sandbox.
    """
    try:
        sandbox = allocation_unit.sandbox
    except ObjectDoesNotExist:
        sandbox = None

    if sandbox and sandbox.locked:
        raise exceptions.ValidationError("Sandbox ID={} is locked.".format(sandbox.id))

    if any([stage.is_running for stage in allocation_unit.allocation_request.stages.all()]):
        raise exceptions.ValidationError(
            'Create sandbox allocation request ID={} has not finished yet.'.
            format(allocation_unit.allocation_request.id)
        )

    request = CleanupRequest.objects.create(allocation_unit=allocation_unit)
    LOG.info("CleanupRequest created", request=request, sandbox=sandbox)

    enqueue_request(request, sandbox)

    return request


def enqueue_request(request: CleanupRequest, sandbox: Optional[Sandbox]) -> None:
    stg1 = CleanupStage.objects.create(request=request)

    queue = django_rq.get_queue(config.OPENSTACK_QUEUE,
                                default_timeout=config.SANDBOX_DELETE_TIMEOUT)
    queue.enqueue(StackDeleteStageManager().run, stage=stg1, sandbox=sandbox)


class StackDeleteStageManager:
    def __init__(self):
        self._client = None

    @property
    def client(self):
        if not self._client:
            self._client = utils.get_ostack_client()
        return self._client

    def run(self, stage: CleanupStage, sandbox: Sandbox) -> None:
        """Run the stage."""
        try:
            stage.start = timezone.now()
            stage.save()
            LOG.info("DeleteStage started", stage=stage, sandbox=sandbox)
            self.delete_sandbox(sandbox, stage.request.allocation_unit)
        except Exception as ex:
            stage.mark_failed(ex)
            raise
        finally:
            stage.end = timezone.now()
            stage.save()

    def delete_sandbox(self, sandbox: Sandbox, alloc_unit: SandboxAllocationUnit,
                       hard=False) -> None:
        """Deletes given sandbox. Hard specifies whether to use hard delete.
        On soft delete raises ValidationError if any sandbox is locked."""
        stack_name = alloc_unit.get_stack_name()

        if sandbox:
            sandbox.delete()
        alloc_unit.delete()

        LOG.info("Sandbox deleted from DB", sandbox=sandbox, alloc_unit=alloc_unit)

        if hard:
            self.client.delete_sandbox_hard(stack_name)
        else:
            self.client.delete_sandbox(stack_name)

        self.wait_for_stack_deletion(stack_name)

        LOG.info("Sandbox deleted successfully from OpenStack", sandbox_stack_name=stack_name)

    def wait_for_stack_deletion(self, stack_name: str) -> None:
        """Wait for stack deletion."""
        def sandbox_delete_check():
            stacks = self.client.list_sandboxes()
            if stack_name in stacks:
                stack_status = stacks[stack_name].stack_status
                return stack_status.endswith("FAILED")
            return True

        utils.wait_for(sandbox_delete_check, config.SANDBOX_DELETE_TIMEOUT, freq=10, initial_wait=3,
                       errmsg="Sandbox deletion exceeded timeout of {} sec. Sandbox: {}"
                       .format(config.SANDBOX_BUILD_TIMEOUT, str(stack_name)))
