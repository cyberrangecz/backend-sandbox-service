from django.contrib import admin

from .import models


class ShowIdAdmin(admin.ModelAdmin):
    # show id in the web admin
    readonly_fields = ('id',)


admin.site.register(models.AnsibleAllocationStage, ShowIdAdmin)
admin.site.register(models.AnsibleCleanupStage, ShowIdAdmin)
admin.site.register(models.AnsibleOutput, ShowIdAdmin)
# admin.site.register(models.DockerContainer, ShowIdAdmin)
admin.site.register(models.DockerContainer)
