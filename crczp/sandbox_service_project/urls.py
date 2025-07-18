"""crczp.sandbox_service_project URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/2.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.contrib import admin
from django.urls import path, include

from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView

api_patterns = [
    path('admin', admin.site.urls, name='admin'),

    # OpenAPI schema JSON
    path('schema/', SpectacularAPIView.as_view(), name='schema'),

    # Swagger UI
    path('doc/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),

    # Optional: Redoc UI
    path('redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),

    path('django-rq/', include('django_rq.urls')),

    # Include your app URLs
    path('', include('crczp.sandbox_ansible_app.urls')),
    path('', include('crczp.sandbox_definition_app.urls')),
    path('', include('crczp.sandbox_instance_app.urls')),
    path('', include('crczp.sandbox_cloud_app.urls')),
]

urlpatterns = [
    path(settings.URL_PREFIX, include(api_patterns)),
]
