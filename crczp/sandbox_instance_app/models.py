"""Database models for sandbox instance app."""

from functools import partial
from typing import override

import structlog
from django.conf import settings
from django.contrib.auth.models import User
from django.db import models, transaction
from django.utils import timezone

from crczp.sandbox_common_lib import utils
from crczp.sandbox_definition_app.models import Definition
from crczp.sandbox_instance_app.lib.email_notifications import send_email, validate_emails_enabled

DEFAULT_SANDBOX_UUID = '1'
LOG = structlog.get_logger()


class Pool(models.Model):
    """Represents a pool of sandboxes sharing a common definition and key-pair."""

    definition = models.ForeignKey(
        Definition,
        on_delete=models.PROTECT,
    )
    max_size = models.IntegerField(
        help_text='Maximum amount of Allocation Units associated with this pool.'
    )
    size = models.PositiveIntegerField(
        default=0,
        help_text='Current amount of Allocation Units associated with this pool.',
    )
    private_management_key = models.TextField(help_text='Private key for management access.')
    public_management_key = models.TextField(help_text='Public key for management access.')
    management_certificate = models.TextField(
        help_text='Certificate for windows management access.'
    )
    uuid = models.TextField(default=utils.get_simple_uuid)
    rev = models.TextField(help_text='Definition revision used for sandboxes.')
    rev_sha = models.TextField(help_text='SHA of the Definition revision.')
    created_by = models.ForeignKey(
        User, on_delete=models.PROTECT, null=True, help_text='The user that created this pool.'
    )
    send_emails = models.BooleanField(default=False, validators=[validate_emails_enabled])
    comment = models.CharField(
        default='', blank=True, max_length=256, help_text='Comment about specifics of this pool'
    )
    visible = models.BooleanField(
        default=True,
        help_text=(
            'Visibility to other instructors. If False, pool is only visible to owner and admins.'
        ),
    )

    class Meta:  # pylint: disable=too-few-public-methods
        """Meta options for Pool model."""

        ordering = ['id']

    @override
    def __str__(self) -> str:
        return (
            f'ID: {self.id}, DEFINITION: {self.definition.id}, MAX_SIZE: {self.max_size}, '
            f'REV: {self.rev}'
        )

    def get_pool_prefix(self) -> str:
        """Returns a prefix of this pool."""
        prefix = settings.CRCZP_SERVICE_CONFIG.stack_name_prefix
        return f'{prefix}-p{self.id:010d}'

    def get_keypair_name(self) -> str:
        """Returns a name of the management key-pair for this pool."""
        return f'{self.get_pool_prefix()}-{self.uuid}'

    @property
    def ssh_keypair_name(self) -> str:
        """Return the SSH key-pair name for this pool."""
        return self.get_keypair_name() + '-ssh'

    @property
    def certificate_keypair_name(self) -> str:
        """Return the certificate key-pair name for this pool."""
        return self.get_keypair_name() + '-cert'


class SandboxAllocationUnit(models.Model):
    """Represents a single sandbox allocation unit within a pool."""

    pool = models.ForeignKey(
        Pool,
        on_delete=models.PROTECT,
        related_name='allocation_units',
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        null=True,
        help_text='The user that created this sandbox allocation unit.',
    )
    comment = models.CharField(
        default='', blank=True, max_length=256, help_text='Comment about specifics of this sandbox'
    )

    def get_stack_name(self) -> str:
        """Returns a name of the stack for this sandbox"""
        return f'{self.pool.get_pool_prefix()}-s{self.id:010d}'


class Sandbox(models.Model):
    """Represents an allocated sandbox with user access keys."""

    id = models.CharField(
        primary_key=True,
        auto_created=False,
        max_length=36,
        default=DEFAULT_SANDBOX_UUID,
        editable=False,
    )
    allocation_unit = models.OneToOneField(
        SandboxAllocationUnit,
        on_delete=models.PROTECT,
        related_name='sandbox',
    )
    private_user_key = models.TextField(help_text='Private key for user access.')
    public_user_key = models.TextField(help_text='Public key for management access.')
    ready = models.BooleanField(
        default=False, help_text='Is the sandbox ready to use for trainings.'
    )

    class Meta:  # pylint: disable=too-few-public-methods
        """Meta options for Sandbox model."""

        ordering = ['id']

    @override
    def __str__(self) -> str:
        return (
            f'ID: {self.id}, ALLOCATION_UNIT: {self.allocation_unit.id}, '
            f'LOCK: {self.lock.id if hasattr(self, "lock") else None}'
        )


class SandboxLock(models.Model):
    """Represents a lock on a sandbox preventing concurrent access."""

    sandbox = models.OneToOneField(
        Sandbox,
        on_delete=models.PROTECT,
        related_name='lock',
    )
    created_by = models.ForeignKey(
        User, on_delete=models.PROTECT, null=True, help_text='The user that created this lock.'
    )

    @override
    def __str__(self) -> str:
        return f'ID: {self.id}, Sandbox: {self.sandbox.id}'


class PoolLock(models.Model):
    """Represents a lock on a pool used during active training sessions."""

    pool = models.OneToOneField(
        Pool,
        on_delete=models.PROTECT,
        related_name='lock',
    )

    training_access_token = models.CharField(max_length=256, default=None, null=True)

    @override
    def __str__(self) -> str:
        return f'ID: {self.id}, Pool: {self.pool.id}'


class SandboxRequest(models.Model):
    """Abstract base class for Sandbox Requests."""

    id: int
    created = models.DateTimeField(default=timezone.now)

    class Meta:  # pylint: disable=too-few-public-methods
        """Meta options for SandboxRequest model."""

        abstract = True
        ordering = ['created']

    @override
    def __str__(self) -> str:
        return f'ID: {self.id}, CREATED: {self.created}'


class AllocationRequest(SandboxRequest):
    """Represents a request to allocate a sandbox for an allocation unit."""

    allocation_unit = models.OneToOneField(
        SandboxAllocationUnit,
        on_delete=models.CASCADE,
        related_name='allocation_request',
    )

    @property
    def is_finished(self) -> bool:
        """Whether all stages are finished."""
        return self.stages.filter(finished=False).count() == 0

    @override
    def __str__(self) -> str:
        return str(super().__str__()) + f', ALLOCATION_UNIT: {self.allocation_unit.id}'


class CleanupRequest(SandboxRequest):
    """Represents a request to clean up and delete a sandbox allocation unit."""

    allocation_unit = models.OneToOneField(
        SandboxAllocationUnit,
        on_delete=models.CASCADE,
        related_name='cleanup_request',
    )

    @property
    def is_finished(self) -> bool:
        """Whether all stages are finished."""
        return self.stages.filter(finished=False).count() == 0

    @property
    def is_failed(self) -> bool:
        """Whether all stages are finished."""
        return self.stages.filter(failed=True).count() > 0

    @override
    def __str__(self) -> str:
        return str(super().__str__()) + f', ALLOCATION_UNIT: {self.allocation_unit.id}'


class Stage(models.Model):
    """Abstract base class for stages."""

    start = models.DateTimeField(
        null=True, default=None, help_text='Timestamp indicating when the stage execution started.'
    )
    end = models.DateTimeField(
        null=True, default=None, help_text='Timestamp indicating when the stage execution ended.'
    )
    failed = models.BooleanField(
        default=False, help_text='Indicates whether the stage execution failed.'
    )
    error_message = models.TextField(
        null=True, default=None, help_text='Error message describing the potential error.'
    )
    finished = models.BooleanField(
        default=False, help_text='Indicates whether the stage execution has finished.'
    )

    id: int

    class Meta:  # pylint: disable=too-few-public-methods
        """Meta options for Stage model."""

        abstract = True
        ordering = ['id']

    @override
    def __str__(self) -> str:
        return (
            f'ID: {self.id}, START: {self.start}, END: {self.end}, FAILED: {self.failed}, '
            f'ERROR: {self.error_message}'
        )


class AllocationStage(Stage):
    """Concrete stage associated with an allocation request."""

    allocation_request_fk_many = models.ForeignKey(
        AllocationRequest, on_delete=models.CASCADE, related_name='stages'
    )


class CleanupStage(Stage):
    """Concrete stage associated with a cleanup request."""

    cleanup_request_fk_many = models.ForeignKey(
        CleanupRequest, on_delete=models.CASCADE, related_name='stages'
    )


class StackAllocationStage(AllocationStage):
    """Allocation stage tracking Terraform stack creation."""

    allocation_request = models.OneToOneField(
        AllocationRequest,
        on_delete=models.CASCADE,
    )
    status = models.CharField(null=True, max_length=30, help_text='Stack status')
    status_reason = models.TextField(null=True, help_text='Stack status reason')

    @override
    def __str__(self) -> str:
        return (
            str(super().__str__()) + f', REQUEST: {self.allocation_request}, STATUS: {self.status},'
            f' STATUS_REASON: {self.status_reason}'
        )


class StackCleanupStage(CleanupStage):
    """Cleanup stage tracking Terraform stack deletion."""

    cleanup_request = models.OneToOneField(
        CleanupRequest,
        on_delete=models.CASCADE,
    )

    @override
    def __str__(self) -> str:
        return str(super().__str__()) + f', REQUEST: {self.cleanup_request}'


class RQJob(models.Model):
    """Abstract base class for RQ job tracking models."""

    job_id = models.TextField()

    class Meta:  # pylint: disable=too-few-public-methods
        """Meta options for RQJob model."""

        abstract = True


class AllocationRQJob(RQJob):
    """Tracks the RQ job ID for an allocation stage."""

    allocation_stage = models.OneToOneField(
        AllocationStage,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name='rq_job',
    )

    @override
    def __str__(self) -> str:
        return f'STAGE: {self.allocation_stage.id}, JOB_ID: {self.job_id}'


class CleanupRQJob(RQJob):
    """Tracks the RQ job ID for a cleanup stage."""

    cleanup_stage = models.OneToOneField(
        CleanupStage,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name='rq_job',
    )

    @override
    def __str__(self) -> str:
        return f'STAGE: {self.cleanup_stage.id}, JOB_ID: {self.job_id}'


class ExternalDependency(models.Model):
    """Abstract base class for external allocation dependencies."""

    allocation_stage = models.OneToOneField(AllocationStage, on_delete=models.CASCADE)

    class Meta:  # pylint: disable=too-few-public-methods
        """Meta options for ExternalDependency model."""

        abstract = True


class ExternalDependencyCleanup(models.Model):
    """Abstract base class for external cleanup dependencies."""

    cleanup_stage = models.OneToOneField(CleanupStage, on_delete=models.CASCADE)

    class Meta:  # pylint: disable=too-few-public-methods
        """Meta options for ExternalDependencyCleanup model."""

        abstract = True


class TerraformOutput(models.Model):
    """Abstract base class for storing Terraform process output lines."""

    content = models.TextField()

    id: int

    class Meta:  # pylint: disable=too-few-public-methods
        """Meta options for TerraformOutput model."""

        abstract = True
        ordering = ['id']

    @override
    def __str__(self) -> str:
        return f'ID: {self.id}, CONTENT: {self.content}'


class AllocationTerraformOutput(TerraformOutput):
    """Stores Terraform output lines for an allocation stage."""

    allocation_stage = models.ForeignKey(
        AllocationStage, on_delete=models.CASCADE, related_name='terraform_outputs'
    )

    @override
    def __str__(self) -> str:
        return f'{str(super().__str__())} STAGE: {self.allocation_stage.id}'


class CleanupTerraformOutput(TerraformOutput):
    """Stores Terraform output lines for a cleanup stage."""

    cleanup_stage = models.ForeignKey(
        CleanupStage, on_delete=models.CASCADE, related_name='terraform_outputs'
    )

    @override
    def __str__(self) -> str:
        return f'{str(super().__str__())} STAGE: {self.cleanup_stage.id}'


class TerraformStack(ExternalDependency):
    """Tracks the Terraform stack process associated with an allocation stage."""

    stack_id = models.TextField()

    @override
    def __str__(self) -> str:
        return f'STAGE: {self.allocation_stage.id}, STACK: {self.stack_id}'


class SystemProcess(ExternalDependency):
    """Tracks a system process associated with an allocation stage."""

    process_id = models.TextField()

    @override
    def __str__(self) -> str:
        return f'STAGE: {self.allocation_stage.id}, PROCESS: {self.process_id}'


class SandboxNetbirdAccess(models.Model):
    """
    Stores the single shared Netbird "access" group and setup key created for a
    sandbox. One row per sandbox: every VPN entrypoint's policy and routes use
    this one access group as their source/access-control group, and the access
    setup key is the single key exposed to clients via the VPN API endpoint.

    All fields are nullable so that a partial-failure state can be persisted:
    the cleanup path tolerates nulls and issues 404-tolerant deletes.
    """

    sandbox = models.OneToOneField(
        Sandbox,
        on_delete=models.CASCADE,
        related_name='netbird_access',
        help_text='Sandbox these access resources belong to.',
    )
    access_group_id = models.CharField(
        max_length=255,
        null=True,
        default=None,
        help_text='Netbird group ID shared by all client peers of the sandbox.',
    )
    access_setup_key_id = models.CharField(
        max_length=255,
        null=True,
        default=None,
        help_text='Netbird setup key ID for the shared access group.',
    )
    access_setup_key_value = models.TextField(
        null=True,
        default=None,
        help_text='Plaintext setup key for the shared access group.',
    )
    dns_nameserver_group_id = models.CharField(
        max_length=255,
        null=True,
        default=None,
        help_text='Netbird DNS nameserver group ID distributed to the access group.',
    )

    class Meta:
        ordering = ['id']
        verbose_name_plural = 'sandbox netbird access'


class SandboxNetbirdResources(models.Model):
    """
    Stores IDs of Netbird control-plane objects created for one VPN entrypoint
    within a sandbox. One row per entrypoint.

    All fields are nullable so that a partial-failure state can be persisted:
    the cleanup path tolerates nulls and issues 404-tolerant deletes.
    """

    sandbox = models.ForeignKey(
        Sandbox,
        on_delete=models.CASCADE,
        related_name='netbird_resources',
        help_text='Sandbox these resources belong to.',
    )
    entrypoint_host_name = models.CharField(
        max_length=255,
        help_text='Name of the topology host configured as VPN entrypoint.',
    )
    host_group_id = models.CharField(
        max_length=255,
        null=True,
        default=None,
        help_text='Netbird group ID for the entrypoint peer.',
    )
    host_setup_key_id = models.CharField(
        max_length=255,
        null=True,
        default=None,
        help_text='Netbird setup key ID used by the agent on the entrypoint VM.',
    )
    host_setup_key_value = models.TextField(
        null=True,
        default=None,
        help_text='Plaintext setup key for the entrypoint host agent.',
    )
    route_ids = models.TextField(
        null=True,
        default=None,
        help_text='Comma-separated Netbird route IDs for this entrypoint.',
    )
    route_cidrs = models.TextField(
        null=True,
        default=None,
        help_text='Comma-separated CIDR strings for the routes of this entrypoint.',
    )
    policy_id = models.CharField(
        max_length=255,
        null=True,
        default=None,
        help_text='Netbird access policy ID permitting client-to-host traffic.',
    )

    class Meta:
        ordering = ['id']
        unique_together = [('sandbox', 'entrypoint_host_name')]
        verbose_name_plural = 'sandbox netbird resources'

    def get_route_id_list(self) -> list[str]:
        if not self.route_ids:
            return []
        return [r for r in self.route_ids.split(',') if r]

    def set_route_id_list(self, ids: list[str]) -> None:
        self.route_ids = ','.join(ids)

    def get_route_cidr_list(self) -> list[str]:
        if not self.route_cidrs:
            return []
        return [r for r in self.route_cidrs.split(',') if r]

    def set_route_cidr_list(self, cidrs: list[str]) -> None:
        self.route_cidrs = ','.join(cidrs)


class SandboxRequestGroup(models.Model):
    """
    Represents allocation/cleanup requests created at the same time.

    Keeps track of the request progress and sends email notifications.
    """

    pool = models.ForeignKey(Pool, on_delete=models.CASCADE)
    unit_count = models.IntegerField()
    email = models.EmailField()
    failed_count = models.IntegerField(default=0)
    finished_count = models.IntegerField(default=0)

    def on_allocation_fail(self, exc: Exception) -> None:
        """Handle a sandbox allocation failure: track counts and send notification if first fail."""
        with transaction.atomic():
            self.refresh_from_db()
            if self.failed_count == 0:
                transaction.on_commit(partial(self._send_fail_notification, exc=exc))
                LOG.debug('Sandbox allocation Failure email notification sent.')
            self.failed_count += 1
            self.finished_count += 1
            self.save()
            if self.finished_count == self.unit_count:
                transaction.on_commit(self._send_summary_notification)
                LOG.debug('Sandbox allocation End email notification sent.')

    def on_allocation_end(self) -> None:
        """Handle a sandbox allocation completion: track counts and send summary if all done."""
        with transaction.atomic():
            self.refresh_from_db()
            self.finished_count += 1
            self.save()
            if self.finished_count == self.unit_count:
                transaction.on_commit(self._send_summary_notification)
                LOG.debug('Sandbox allocation End email notification sent.')

    def _send_fail_notification(self, exc: Exception) -> None:
        body = f"""
        Something went wrong during sandbox allocation in Pool {self.pool.id}.

        Error detail: {str(exc)}
        """
        send_email(
            self.email,
            f'CRCZP Pool {self.pool.id} - FAILED sandbox allocation',
            body,
            settings.CRCZP_CONFIG,
        )

    def _send_summary_notification(self) -> None:
        try:
            body = f"""
            All allocations you created in Pool {self.pool.id} have finished.

            Successful - {self.finished_count - self.failed_count}
            Failed - {self.failed_count}
            """
            send_email(
                self.email,
                f'CRCZP Pool {self.pool.id} - FINAL sandbox allocations report',
                body,
                settings.CRCZP_CONFIG,
            )
        finally:
            self.delete()
