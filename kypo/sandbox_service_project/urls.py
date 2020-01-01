"""kypo.sandbox_service_project URL Configuration

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
from django.contrib import admin
from django.urls import path, re_path, include
from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi

from ..sandbox_common.config import config


schema_view = get_schema_view(
    openapi.Info(
        title="KYPO2 OpenStack REST API documentation",
        default_version=config.VERSION,
        description='',
    ),
    validators=[],
    public=True,
    permission_classes=(permissions.AllowAny,),
)

urlpatterns = [
    path('admin/', admin.site.urls, name='admin'),

    path('doc/', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
    re_path(r'^doc(?P<format>\.json|\.yaml)$', schema_view.without_ui(cache_timeout=0),
            name='schema-json'),

    path('django-rq/', include('django_rq.urls')),

    # Include Apps' URLs
    path('', include('kypo.sandbox_ansible_runs.urls')),
    path('', include('kypo.sandbox_definitions.urls')),
    path('', include('kypo.sandbox_instances.urls')),
]

# Prefixing urls
urlpatterns = [
    path(config.URL_PREFIX, include(urlpatterns)),
]
