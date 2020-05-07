"""Sandbox Definition App urls."""

from django.urls import path

from kypo.sandbox_definition_app import views


urlpatterns = [
    path('definitions', views.DefinitionList.as_view(), name='definition-list'),
    path('definitions/<int:definition_id>', views.DefinitionDetail.as_view(),
         name='definition-detail'),
    path('definitions/<int:definition_id>/refs', views.DefinitionRefs.as_view(),
         name='definition-rev-list'),
]
