# Generated by Django 2.2.28 on 2022-05-10 13:40

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('sandbox_instance_app', '0004_allocationterraformoutput_cleanupterraformoutput'),
        ('sandbox_ansible_app', '0004_auto_20210507_1234'),
    ]

    operations = [
        migrations.RenameModel(
            old_name='DockerContainer',
            new_name='Container',
        ),
        migrations.RenameModel(
            old_name='DockerContainerCleanup',
            new_name='ContainerCleanup',
        ),
        migrations.RenameField(
            model_name='container',
            old_name='container_id',
            new_name='container_name',
        ),
        migrations.RenameField(
            model_name='containercleanup',
            old_name='container_id',
            new_name='container_name',
        ),
    ]
