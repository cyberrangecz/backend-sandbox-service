from django.contrib import admin

from crczp.sandbox_ansible_app import models


class ShowIdAdmin(admin.ModelAdmin):
    # show id in the web admin
    readonly_fields = ('id',)


admin.site.register(models.NetworkingAnsibleAllocationStage, ShowIdAdmin)
admin.site.register(models.NetworkingAnsibleCleanupStage, ShowIdAdmin)
admin.site.register(models.UserAnsibleAllocationStage, ShowIdAdmin)
admin.site.register(models.UserAnsibleCleanupStage, ShowIdAdmin)
admin.site.register(models.AllocationAnsibleOutput, ShowIdAdmin)
admin.site.register(models.CleanupAnsibleOutput, ShowIdAdmin)
admin.site.register(models.Container)
