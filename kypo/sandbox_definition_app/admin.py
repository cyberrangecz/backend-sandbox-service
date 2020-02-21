from django.contrib import admin

from kypo.sandbox_definition_app import models


class ShowIdAdmin(admin.ModelAdmin):
    # show id in the web admin
    readonly_fields = ('id',)


admin.site.register(models.Definition, ShowIdAdmin)
