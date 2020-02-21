from django.db import models

from kypo.sandbox_instance_app.models import ExternalDependency, AllocationStage, CleanupStage, StageType


class AnsibleAllocationStage(AllocationStage):
    type = StageType.ANSIBLE

    repo_url = models.TextField()
    rev = models.TextField()

    def __str__(self):

        return super().__str__() + \
               ", REPO_URL: {0.repo_url}, REV: {0.rev}".format(self)


class AnsibleCleanupStage(CleanupStage):
    type = StageType.ANSIBLE

    allocation_stage = models.OneToOneField(
        AnsibleAllocationStage,
        on_delete=models.CASCADE,
        related_name='cleanup_stage',
    )

    def __str__(self):
        return super().__str__() + \
               ", ALLOCATION_STAGE: {0.allocation_stage}".format(self)


class AnsibleOutput(models.Model):
    stage = models.ForeignKey(
        AnsibleAllocationStage,
        on_delete=models.CASCADE,
        related_name='outputs'
    )
    content = models.TextField()

    class Meta:
        ordering = ['id']

    def __str__(self):
        return "ID: {0.id}, STAGE: {0.stage.id}, CONTENT: {0.content}".format(self)


class DockerContainer(ExternalDependency):
    stage = models.OneToOneField(
        AnsibleAllocationStage,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name='container',
    )
    container_id = models.TextField()

    def __str__(self):
        return "STAGE: {0.stage.id}, CONTAINER: {0.container_id}".format(self)
