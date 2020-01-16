from django.db import models


class Definition(models.Model):
    name = models.CharField(max_length=100)
    url = models.TextField()
    rev = models.TextField(default='master')

    class Meta:
        ordering = ['id']

    def __str__(self):
        return "ID: {0.id}, NAME: {0.name}, URL: {0.url}, REV: {0.rev}".format(self)
