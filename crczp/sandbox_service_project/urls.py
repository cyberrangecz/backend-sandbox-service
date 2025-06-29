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
import drf_yasg.openapi as openapi
from django.conf import settings
from django.contrib import admin
from django.urls import path, re_path, include

from drf_yasg.views import get_schema_view
from rest_framework import permissions


VERSION = 'v1'
URL_PREFIX = f'{settings.CRCZP_SERVICE_CONFIG.microservice_name}/api/{VERSION}/'

schema_view = get_schema_view(
    openapi.Info(
        title="CRCZP OpenStack REST API documentation",
        default_version=VERSION,
        description="",
    ),
    public=True,
    permission_classes=(permissions.AllowAny,),
)

urlpatterns = [
    path('admin', admin.site.urls, name='admin'),

    path('doc', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
    re_path(r'^doc(?P<format>\.json|\.yaml)$', schema_view.without_ui(cache_timeout=0),
            name='schema-json'),

    path('django-rq/', include('django_rq.urls')),

    # Include Apps' URLs
    path('', include('crczp.sandbox_ansible_app.urls')),
    path('', include('crczp.sandbox_definition_app.urls')),
    path('', include('crczp.sandbox_instance_app.urls')),
    path('', include('crczp.sandbox_cloud_app.urls')),
]

# Prefixing urls
urlpatterns = [
    path(URL_PREFIX, include(urlpatterns)),
]
