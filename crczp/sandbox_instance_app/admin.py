from django.contrib import admin

from crczp.sandbox_instance_app import models


class ShowIdAdmin(admin.ModelAdmin):
    # show id in the web admin
    readonly_fields = ('id',)


admin.site.register(models.Pool, ShowIdAdmin)
admin.site.register(models.SandboxAllocationUnit, ShowIdAdmin)
admin.site.register(models.SandboxLock, ShowIdAdmin)
admin.site.register(models.PoolLock, ShowIdAdmin)
admin.site.register(models.Sandbox, ShowIdAdmin)
admin.site.register(models.AllocationRequest, ShowIdAdmin)
admin.site.register(models.CleanupRequest, ShowIdAdmin)

admin.site.register(models.AllocationStage, ShowIdAdmin)
admin.site.register(models.StackAllocationStage, ShowIdAdmin)
admin.site.register(models.CleanupStage, ShowIdAdmin)
admin.site.register(models.StackCleanupStage, ShowIdAdmin)

admin.site.register(models.TerraformStack)
admin.site.register(models.AllocationTerraformOutput, ShowIdAdmin)
admin.site.register(models.CleanupTerraformOutput, ShowIdAdmin)

admin.site.register(models.SandboxRequestGroup, ShowIdAdmin)
