import structlog
from functools import partial
from django.conf import settings
from django.db import models, transaction
from django.utils import timezone
from django.contrib.auth.models import User

from kypo.sandbox_common_lib import utils
from kypo.sandbox_definition_app.models import Definition
from kypo.sandbox_instance_app.lib.email_notifications import send_email, validate_emails_enabled
from kypo.sandbox_service_project.settings import KYPO_CONFIG

DEFAULT_SANDBOX_UUID = '1'
LOG = structlog.get_logger()


class Pool(models.Model):
    definition = models.ForeignKey(
        Definition,
        on_delete=models.PROTECT,
    )
    max_size = models.IntegerField(
        help_text='Maximum amount of Allocation Units associated with this pool.')
    size = models.PositiveIntegerField(
        default=0,
        help_text='Current amount of Allocation Units associated with this pool.',
    )
    private_management_key = models.TextField(
        help_text='Private key for management access.'
    )
    public_management_key = models.TextField(
        help_text='Public key for management access.'
    )
    management_certificate = models.TextField(
        help_text='Certificate for windows management access.'
    )
    uuid = models.TextField(default=utils.get_simple_uuid)
    rev = models.TextField(
        help_text='Definition revision used for sandboxes.'
    )
    rev_sha = models.TextField(
        help_text='SHA of the Definition revision.'
    )
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True,
                                   help_text='The user that created this pool.')
    send_emails = models.BooleanField(default=False, validators=[validate_emails_enabled])
    comment = models.CharField(
        default='',
        blank=True,
        max_length=256,
        help_text='Comment about specifics of this pool'
    )
    visible = models.BooleanField(
        default=True,
        help_text='Visibility to other instructors. If False, pool is only visible to owner and admins.'
    )

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f'ID: {self.id}, DEFINITION: {self.definition.id}, MAX_SIZE: {self.max_size}, ' \
               f'REV: {self.rev}'

    def get_pool_prefix(self) -> str:
        """Returns a prefix of this pool."""
        prefix = settings.KYPO_SERVICE_CONFIG.stack_name_prefix
        return f'{prefix}-p{self.id:010d}'

    def get_keypair_name(self) -> str:
        """Returns a name of the management key-pair for this pool."""
        return f'{self.get_pool_prefix()}-{self.uuid}'

    @property
    def ssh_keypair_name(self) -> str:
        return self.get_keypair_name() + '-ssh'

    @property
    def certificate_keypair_name(self) -> str:
        return self.get_keypair_name() + '-cert'


class SandboxAllocationUnit(models.Model):
    pool = models.ForeignKey(
        Pool,
        on_delete=models.PROTECT,
        related_name='allocation_units',
    )
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True,
                                   help_text='The user that created this sandbox allocation unit.')
    comment = models.CharField(
        default='',
        blank=True,
        max_length=256,
        help_text='Comment about specifics of this sandbox'
    )

    def get_stack_name(self) -> str:
        """Returns a name of the stack for this sandbox"""
        return f'{self.pool.get_pool_prefix()}-s{self.id:010d}'


class Sandbox(models.Model):
    id = models.CharField(primary_key=True, auto_created=False, max_length=36,
                          default=DEFAULT_SANDBOX_UUID, editable=False)
    allocation_unit = models.OneToOneField(
        SandboxAllocationUnit,
        on_delete=models.PROTECT,
        related_name='sandbox',
    )
    private_user_key = models.TextField(
        help_text='Private key for user access.'
    )
    public_user_key = models.TextField(
        help_text='Public key for management access.'
    )

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f'ID: {self.id}, ALLOCATION_UNIT: {self.allocation_unit.id}, ' \
               f'LOCK: {self.lock.id if hasattr(self, "lock") else None}'


class SandboxLock(models.Model):
    sandbox = models.OneToOneField(
        Sandbox,
        on_delete=models.PROTECT,
        related_name='lock',
    )
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True,
                                   help_text='The user that created this lock.')

    def __str__(self):
        return f'ID: {self.id}, Sandbox: {self.sandbox.id}'


class PoolLock(models.Model):
    pool = models.OneToOneField(
        Pool,
        on_delete=models.PROTECT,
        related_name='lock',
    )

    def __str__(self):
        return f'ID: {self.id}, Pool: {self.pool.id}'


class SandboxRequest(models.Model):
    """Abstract base class for Sandbox Requests."""
    created = models.DateTimeField(default=timezone.now)

    class Meta:
        abstract = True
        ordering = ['created']

    def __str__(self):
        return f'ID: {self.id}, CREATED: {self.created}'


class AllocationRequest(SandboxRequest):
    allocation_unit = models.OneToOneField(
        SandboxAllocationUnit,
        on_delete=models.CASCADE,
        related_name='allocation_request',
    )

    @property
    def is_finished(self):
        """Whether all stages are finished."""
        return self.stages.filter(finished=False).count() == 0

    def __str__(self):
        return super().__str__() + f', ALLOCATION_UNIT: {self.allocation_unit.id}'


class CleanupRequest(SandboxRequest):
    allocation_unit = models.OneToOneField(
        SandboxAllocationUnit,
        on_delete=models.CASCADE,
        related_name='cleanup_request',
    )

    @property
    def is_finished(self):
        """Whether all stages are finished."""
        return self.stages.filter(finished=False).count() == 0

    def __str__(self):
        return super().__str__() + f', ALLOCATION_UNIT: {self.allocation_unit.id}'


class Stage(models.Model):
    """Abstract base class for stages."""
    start = models.DateTimeField(null=True, default=None,
                                 help_text='Timestamp indicating when the stage execution started.')
    end = models.DateTimeField(null=True, default=None,
                               help_text='Timestamp indicating when the stage execution ended.')
    failed = models.BooleanField(default=False,
                                 help_text='Indicates whether the stage execution failed.')
    error_message = models.TextField(null=True, default=None,
                                     help_text='Error message describing the potential error.')
    finished = models.BooleanField(default=False,
                                   help_text='Indicates whether the stage execution has finished.')

    class Meta:
        abstract = True
        ordering = ['id']

    def __str__(self):
        return f'ID: {self.id}, START: {self.start}, END: {self.end}, FAILED: {self.failed}, ' \
               f'ERROR: {self.error_message}'


class AllocationStage(Stage):
    allocation_request_fk_many = models.ForeignKey(
        AllocationRequest,
        on_delete=models.CASCADE,
        related_name='stages'
    )


class CleanupStage(Stage):
    cleanup_request_fk_many = models.ForeignKey(
        CleanupRequest,
        on_delete=models.CASCADE,
        related_name='stages'
    )


class StackAllocationStage(AllocationStage):
    allocation_request = models.OneToOneField(
        AllocationRequest,
        on_delete=models.CASCADE,
    )
    status = models.CharField(null=True, max_length=30, help_text='Stack status')
    status_reason = models.TextField(null=True, help_text='Stack status reason')

    def __str__(self):
        return super().__str__() + f', REQUEST: {self.allocation_request}, STATUS: {self.status},' \
                                   f' STATUS_REASON: {self.status_reason}'


class StackCleanupStage(CleanupStage):
    cleanup_request = models.OneToOneField(
        CleanupRequest,
        on_delete=models.CASCADE,
    )

    def __str__(self):
        return super().__str__() + f', REQUEST: {self.cleanup_request}'


class RQJob(models.Model):
    job_id = models.TextField()

    class Meta:
        abstract = True


class AllocationRQJob(RQJob):
    allocation_stage = models.OneToOneField(
        AllocationStage,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name='rq_job',
    )

    def __str__(self):
        return f'STAGE: {self.allocation_stage.id}, JOB_ID: {self.job_id}'


class CleanupRQJob(RQJob):
    cleanup_stage = models.OneToOneField(
        CleanupStage,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name='rq_job',
    )

    def __str__(self):
        return f'STAGE: {self.cleanup_stage.id}, JOB_ID: {self.job_id}'


class ExternalDependency(models.Model):
    allocation_stage = models.OneToOneField(
        AllocationStage,
        on_delete=models.CASCADE
    )

    class Meta:
        abstract = True


class ExternalDependencyCleanup(models.Model):
    cleanup_stage = models.OneToOneField(
        CleanupStage,
        on_delete=models.CASCADE
    )

    class Meta:
        abstract = True


class TerraformOutput(models.Model):
    content = models.TextField()

    class Meta:
        abstract = True
        ordering = ['id']

    def __str__(self):
        return f'ID: {self.id}, CONTENT: {self.content}'


class AllocationTerraformOutput(TerraformOutput):
    allocation_stage = models.ForeignKey(
        AllocationStage,
        on_delete=models.CASCADE,
        related_name='terraform_outputs'
    )

    def __str__(self):
        return f'{super().__str__()} STAGE: {self.allocation_stage.id}'


class CleanupTerraformOutput(TerraformOutput):
    cleanup_stage = models.ForeignKey(
        CleanupStage,
        on_delete=models.CASCADE,
        related_name='terraform_outputs'
    )

    def __str__(self):
        return f'{super().__str__()} STAGE: {self.cleanup_stage.id}'


class TerraformStack(ExternalDependency):
    stack_id = models.TextField()

    def __str__(self):
        return f'STAGE: {self.allocation_stage.id}, STACK: {self.stack_id}'


class SystemProcess(ExternalDependency):
    process_id = models.TextField()

    def __str__(self):
        return f'STAGE: {self.allocation_stage.id}, PROCESS: {self.process_id}'


class SandboxRequestGroup(models.Model):
    """
    Represents allocation/cleanup requests created at the same time.

    Keeps track of the request progress and sends email notifications.
    """
    pool = models.ForeignKey(Pool, on_delete=models.PROTECT)
    unit_count = models.IntegerField()
    email = models.EmailField()
    failed_count = models.IntegerField(default=0)
    finished_count = models.IntegerField(default=0)

    def on_allocation_fail(self, exc):
        with transaction.atomic():
            self.refresh_from_db()
            if self.failed_count == 0:
                transaction.on_commit(partial(self._send_fail_notification, exc=exc))
                LOG.debug("Sandbox allocation Failure email notification sent.")
            self.failed_count += 1
            self.finished_count += 1
            self.save()
            if self.finished_count == self.unit_count:
                transaction.on_commit(self._send_summary_notification)
                LOG.debug("Sandbox allocation End email notification sent.")

    def on_allocation_end(self):
        with transaction.atomic():
            self.refresh_from_db()
            self.finished_count += 1
            self.save()
            if self.finished_count == self.unit_count:
                transaction.on_commit(self._send_summary_notification)
                LOG.debug("Sandbox allocation End email notification sent.")

    def _send_fail_notification(self, exc):
        body = f"""
        Something went wrong during sandbox allocation in Pool {self.pool.id}.
        
        Error detail: {str(exc)}
        """
        send_email(self.email, f"KYPO Pool {self.pool.id} - FAILED sandbox allocation",
                   body, KYPO_CONFIG)

    def _send_summary_notification(self):
        body = f"""
        All allocations you created in Pool {self.pool.id} have finished.

        Successful - {self.finished_count - self.failed_count}
        Failed - {self.failed_count}
        """
        self.delete()
        send_email(self.email, f"KYPO Pool {self.pool.id} - FINAL sandbox allocations report",
                   body, KYPO_CONFIG)

