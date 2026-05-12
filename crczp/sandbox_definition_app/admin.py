"""Django admin site registrations for the sandbox definition app."""

from django.contrib import admin

from crczp.sandbox_definition_app import models


class ShowIdAdmin(admin.ModelAdmin):
    """Admin model that shows the ID field as read-only."""

    # show id in the web admin
    readonly_fields = ('id',)


admin.site.register(models.Definition, ShowIdAdmin)
