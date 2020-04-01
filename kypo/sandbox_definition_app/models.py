from django.db import models


class Definition(models.Model):
    name = models.CharField(max_length=100, help_text='Name of the definition.')
    url = models.TextField(help_text='URL of the definition.')
    rev = models.TextField(default='master', help_text='Default revision.')

    class Meta:
        ordering = ['id']

    def __str__(self):
        return 'ID: {0.id}, NAME: {0.name}, URL: {0.url}, REV: {0.rev}'.format(self)
