"""Project Quota App urls."""

from django.urls import path
from kypo.sandbox_cloud_app import views
from django.views.decorators.cache import cache_page

urlpatterns = [
    path('info', views.ProjectInfoView.as_view(), name='project-info'),
    path('images', views.ProjectImagesView.as_view(), name='project-images'),
    # save output of view to cache for 1 hour
    path('limits', cache_page(60 * 60)(views.ProjectLimitsView.as_view()), name='project-limits'),
]
