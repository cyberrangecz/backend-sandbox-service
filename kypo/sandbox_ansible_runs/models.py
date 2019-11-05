from django.db import models

from ..sandbox_instances.models import ExternalDependency, Stage


class AnsibleAllocationStage(Stage):
    repo_url = models.TextField()
    rev = models.TextField()

    def __str__(self):

        return super().__str__() + \
               ", REPO_URL: {0.repo_url}, REV: {0.rev}".format(self)


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
    container_id = models.TextField()
