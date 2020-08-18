"""Project Quota App urls."""

from django.urls import path
from kypo.sandbox_cloud_app import views

urlpatterns = [
    path('info', views.ProjectInfo.as_view(), name='project-info')
]
