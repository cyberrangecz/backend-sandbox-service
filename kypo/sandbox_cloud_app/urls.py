"""Project Quota App urls."""

from django.urls import path
from kypo.sandbox_cloud_app import views

urlpatterns = [
    path('quotas', views.ProjectQuotaSet.as_view(), name='project-quota-set'),
]
