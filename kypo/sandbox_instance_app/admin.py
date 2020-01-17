from django.contrib import admin

from .import models


class ShowIdAdmin(admin.ModelAdmin):
    # show id in the web admin
    readonly_fields = ('id',)


admin.site.register(models.Pool, ShowIdAdmin)
admin.site.register(models.SandboxAllocationUnit, ShowIdAdmin)
admin.site.register(models.Lock, ShowIdAdmin)
admin.site.register(models.Sandbox, ShowIdAdmin)
admin.site.register(models.AllocationRequest, ShowIdAdmin)
admin.site.register(models.CleanupRequest, ShowIdAdmin)

admin.site.register(models.AllocationStage, ShowIdAdmin)
admin.site.register(models.StackAllocationStage, ShowIdAdmin)
admin.site.register(models.CleanupStage, ShowIdAdmin)
admin.site.register(models.StackCleanupStage, ShowIdAdmin)

# admin.site.register(models.HeatStack, ShowIdAdmin)
admin.site.register(models.HeatStack)
