"""Sandbox Definition App urls."""

from django.urls import path

from crczp.sandbox_definition_app import views


urlpatterns = [
    path('definitions', views.DefinitionListCreateView.as_view(), name='definition-list'),
    path('definitions/<int:definition_id>', views.DefinitionDetailDeleteView.as_view(),
         name='definition-detail'),
    path('definitions/<int:definition_id>/refs', views.DefinitionRefsListView.as_view(),
         name='definition-rev-list'),
    path('definitions/<int:definition_id>/topology', views.DefinitionTopologyView.as_view(),
         name='definition-topology'),
    path('definitions/<int:definition_id>/local-variables',
         views.LocalSandboxVariablesView.as_view(), name='local-variables'),
    path('definitions/<int:definition_id>/variables',
         views.DefinitionVariablesView.as_view(), name='definition-variables')
]
