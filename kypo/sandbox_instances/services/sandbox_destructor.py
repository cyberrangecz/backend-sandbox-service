from typing import Optional
import django
import django_rq
import structlog
from django.utils import timezone
import django.core.exceptions

from . import utils
from .. import exceptions
from ..config import config
from ..models import Sandbox, SandboxDeleteRequest, DeleteStage, SandboxCreateRequest

LOG = structlog.get_logger()


def delete_sandbox_request(create_request: SandboxCreateRequest) -> SandboxDeleteRequest:
    """
    Create delete request and attempt to delete a sandbox.
    """
    try:
        sandbox = create_request.sandbox
    except django.core.exceptions.ObjectDoesNotExist:
        sandbox = None

    if sandbox and sandbox.locked:
        raise exceptions.ValidationError("Sandbox ID={} is locked.".format(sandbox.id))

    if any([stage.is_running for stage in create_request.stages.all()]):
        raise exceptions.ValidationError('Create sandbox request ID={} has not finished yet.'.format(create_request.id))

    request = SandboxDeleteRequest.objects.create(pool=create_request.pool, sandbox_create_request=create_request)
    LOG.info("SandboxDeleteRequest created", request=request, sandbox=sandbox)

    enqueue_request(request, sandbox, create_request)

    return request


def enqueue_request(request: SandboxDeleteRequest, sandbox: Optional[Sandbox],
                    create_request: SandboxCreateRequest) -> None:
    stg1 = DeleteStage.objects.create(request=request)

    queue = django_rq.get_queue(config.OPENSTACK_QUEUE,
                                default_timeout=config.SANDBOX_DELETE_TIMEOUT)
    queue.enqueue(StackDeleteStageManager().run, stage=stg1, sandbox=sandbox,
                  create_request=create_request)


class StackDeleteStageManager:
    def __init__(self):
        self._client = None

    @property
    def client(self):
        if not self._client:
            self._client = utils.get_ostack_client()
        return self._client

    def run(self, stage: DeleteStage, sandbox: Sandbox, create_request: SandboxCreateRequest) -> None:
        """Run the stage."""
        try:
            stage.start = timezone.now()
            stage.save()
            LOG.info("DeleteStage started", stage=stage, sandbox=sandbox)
            self.delete_sandbox(sandbox, create_request)
        except Exception as ex:
            stage.mark_failed(ex)
            raise
        finally:
            stage.end = timezone.now()
            stage.save()

    def delete_sandbox(self, sandbox: Sandbox, create_request: SandboxCreateRequest,
                       hard=False) -> None:
        """Deletes given sandbox. Hard specifies whether to use hard delete.
        On soft delete raises ValidationError if any sandbox is locked."""
        stack_name = create_request.get_stack_name()

        if sandbox:
            sandbox.delete()
        create_request.delete()

        LOG.info("Sandbox deleted from DB", sandbox=sandbox, create_request=create_request)

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
