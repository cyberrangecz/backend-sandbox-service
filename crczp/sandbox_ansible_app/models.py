"""Django models for Ansible-related sandbox stages and outputs."""

from django.db import models

from crczp.sandbox_instance_app.models import (
    AllocationRequest,
    AllocationStage,
    CleanupRequest,
    CleanupStage,
    ExternalDependency,
    ExternalDependencyCleanup,
)


class AnsibleAllocationStage(AllocationStage):
    """Abstract allocation stage that runs an Ansible playbook."""

    repo_url = models.TextField(help_text='URL of the Ansible repository.')
    rev = models.TextField(help_text='Revision of the Ansible repository.')

    class Meta:  # pylint: disable=too-few-public-methods
        """Meta options for AnsibleAllocationStage."""

        abstract = True

    def __str__(self):
        return super().__str__() + f', REPO_URL: {self.repo_url}, REV: {self.rev}'


class NetworkingAnsibleAllocationStage(AnsibleAllocationStage):
    """Allocation stage for networking Ansible playbook."""

    allocation_request = models.OneToOneField(
        AllocationRequest,
        on_delete=models.CASCADE,
    )

    def __str__(self):
        return super().__str__() + f', REQUEST: {self.allocation_request}'


class UserAnsibleAllocationStage(AnsibleAllocationStage):
    """Allocation stage for user Ansible playbook."""

    allocation_request = models.OneToOneField(
        AllocationRequest,
        on_delete=models.CASCADE,
    )

    def __str__(self):
        return super().__str__() + f', REQUEST: {self.allocation_request}'


class AnsibleCleanupStage(CleanupStage):
    """Abstract cleanup stage that runs an Ansible playbook."""

    class Meta:  # pylint: disable=too-few-public-methods
        """Meta options for AnsibleCleanupStage."""

        abstract = True


class NetworkingAnsibleCleanupStage(AnsibleCleanupStage):
    """Cleanup stage for networking Ansible playbook."""

    cleanup_request = models.OneToOneField(
        CleanupRequest,
        on_delete=models.CASCADE,
    )

    def __str__(self):
        return super().__str__() + f', REQUEST: {self.cleanup_request}'


class UserAnsibleCleanupStage(AnsibleCleanupStage):
    """Cleanup stage for user Ansible playbook."""

    cleanup_request = models.OneToOneField(
        CleanupRequest,
        on_delete=models.CASCADE,
    )

    def __str__(self):
        return super().__str__() + f', REQUEST: {self.cleanup_request}'


class AnsibleOutput(models.Model):
    """Abstract model representing a single line of Ansible output."""

    content = models.TextField()

    class Meta:  # pylint: disable=too-few-public-methods
        """Meta options for AnsibleOutput."""

        abstract = True
        ordering = ['id']

    def __str__(self):
        return f'ID: {self.id}, CONTENT: {self.content}'


class AllocationAnsibleOutput(AnsibleOutput):
    """Ansible output lines associated with an allocation stage."""

    allocation_stage = models.ForeignKey(
        AllocationStage, on_delete=models.CASCADE, related_name='outputs'
    )

    def __str__(self):
        return f'{super().__str__()} STAGE: {self.allocation_stage.id}'


class CleanupAnsibleOutput(AnsibleOutput):
    """Ansible output lines associated with a cleanup stage."""

    cleanup_stage = models.ForeignKey(
        CleanupStage, on_delete=models.CASCADE, related_name='outputs'
    )

    def __str__(self):
        return f'{super().__str__()} STAGE: {self.cleanup_stage.id}'


class Container(ExternalDependency):
    """Docker container created during an allocation Ansible stage."""

    container_name = models.TextField()

    def __str__(self):
        return f'STAGE: {self.allocation_stage.id}, CONTAINER: {self.container_name}'


class ContainerCleanup(ExternalDependencyCleanup):
    """Docker container created during a cleanup Ansible stage."""

    container_name = models.TextField()

    def __str__(self):
        return f'STAGE: {self.cleanup_stage.id}, CONTAINER: {self.container_name}'
