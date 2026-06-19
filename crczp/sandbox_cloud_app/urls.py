"""Project Quota App urls."""

from django.urls import path
from django.views.decorators.cache import cache_page

from crczp.sandbox_cloud_app import views

urlpatterns = [
    path('info', views.ProjectInfoView.as_view(), name='project-info'),
    path('images', views.ProjectImagesView.as_view(), name='project-images'),
    path('flavors', views.ProjectFlavorsView.as_view(), name='project-flavors'),
    # save output of view to cache for 1 hour
    path('limits', cache_page(60 * 60)(views.ProjectLimitsView.as_view()), name='project-limits'),
]
