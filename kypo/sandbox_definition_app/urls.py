"""Sandbox Definition App urls."""

from django.urls import path

from kypo.sandbox_definition_app import views


urlpatterns = [
    path('definitions', views.DefinitionListCreateView.as_view(), name='definition-list'),
    path('definitions/<int:definition_id>', views.DefinitionDetailDeleteView.as_view(),
         name='definition-detail'),
    path('definitions/<int:definition_id>/refs', views.DefinitionRefsListView.as_view(),
         name='definition-rev-list'),
]
