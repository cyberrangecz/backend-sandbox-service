import datetime

import structlog
from kypo.sandbox_common_lib import utils
from kypo.sandbox_cloud_app.lib import projects
from kypo.sandbox_cloud_app import serializers

from rest_framework import generics
from rest_framework.response import Response

from kypo.sandbox_instance_app.models import Pool

from drf_yasg2 import openapi
from drf_yasg2.utils import swagger_auto_schema

from django.core.cache import cache

LOG = structlog.get_logger()
IMAGE_LIST_CACHE_TIMEOUT = None


@utils.add_error_responses_doc('get', [401, 403, 500])
class ProjectInfoView(generics.RetrieveAPIView):
    # Exploitation of the Pool model permissions, Since the Cloud App does not have any models.
    queryset = Pool.objects.none()  # Required for DjangoModelPermissions
    serializer_class = serializers.QuotaSetSerializer

    # noinspection PyMethodMayBeStatic
    @swagger_auto_schema(tags=['cloud'])
    def get(self, request, *args, **kwargs):
        """
        Get the quota set and name of project.
        """
        project_name = projects.get_project_name()
        quota_set = projects.get_quota_set()
        serialized_quota = serializers.QuotaSetSerializer(quota_set)
        return Response({'project_name': project_name, 'quotas': serialized_quota.data})


@utils.add_error_responses_doc('get', [401, 403, 500])
class ProjectImagesView(generics.ListAPIView):
    queryset = Pool.objects.none()
    serializer_class = serializers.ImageSerializer

    @property
    def paginator(self):
        _paginator = super().paginator
        _paginator.sort_by_default_param = 'name'
        _paginator.sorting_default_values = {
            # values replace None during sorting
            "size": float('-inf'),
            "updated_at": datetime.MINYEAR,
        }
        return _paginator

    # noinspection PyMethodMayBeStatic
    @swagger_auto_schema(tags=['cloud'],
                         manual_parameters=[
                            openapi.Parameter('name', openapi.IN_QUERY, type=openapi.TYPE_STRING),
                            openapi.Parameter('os_distro', openapi.IN_QUERY,
                                              type=openapi.TYPE_STRING),
                            openapi.Parameter('os_type', openapi.IN_QUERY,
                                              type=openapi.TYPE_STRING),
                            openapi.Parameter('visibility', openapi.IN_QUERY,
                                              type=openapi.TYPE_STRING),
                            openapi.Parameter('default_user', openapi.IN_QUERY,
                                              type=openapi.TYPE_STRING),
                            openapi.Parameter('munikypo', openapi.IN_QUERY,
                                              description="Returns only images with the attribute "
                                                          "owner_specified.openstack.created_by "
                                                          "set to munikypo",
                                              type=openapi.TYPE_BOOLEAN, default=False),
                            openapi.Parameter('GUI', openapi.IN_QUERY,
                                              description="Returns only images with the attribute "
                                                          "owner_specified.openstack.gui_access"
                                                          "set to true",
                                              type=openapi.TYPE_BOOLEAN, default=False),
                            openapi.Parameter('cached', openapi.IN_QUERY,
                                              description="Performs the faster version of this "
                                                          "endpoint but does retrieve a fresh list"
                                                          " of images.",
                                              type=openapi.TYPE_BOOLEAN, default=False),
                        ])
    def get(self, request, *args, **kwargs):
        """
        Get list of images.
        """
        if request.GET.get('cached') == "true":
            image_set = cache.get("image_list", None)
            if not image_set:
                image_set = projects.list_images()
        else:
            image_set = projects.list_images()
        cache.set("image_list", image_set, IMAGE_LIST_CACHE_TIMEOUT)

        if request.GET.get('munikypo') == "true":
            image_set = [image for image in image_set if
                         image.owner_specified.get('owner_specified.openstack.created_by', 'other')
                         == 'munikypo']
        if request.GET.get('GUI') == "true":
            image_set = [image for image in image_set if
                         image.owner_specified.get('owner_specified.openstack.gui_access', 'other')
                         == 'true']

        if image_set:
            image_attributes = [attribute for attribute in dir(image_set[0])
                                if not attribute.startswith('__')]
            for attribute in image_attributes:
                attribute_filter = request.GET.get(attribute)
                if attribute_filter:
                    image_set = [image for image in image_set if getattr(image, attribute)
                                 and attribute_filter in getattr(image, attribute)]
        serialized_image_set = serializers.ImageSerializer(image_set, many=True)
        page = self.paginate_queryset(serialized_image_set.data)
        if page is not None:
            return self.get_paginated_response(page)
        return Response({'image_set': serialized_image_set.data})


@utils.add_error_responses_doc('get', [401, 403, 500])
class ProjectLimitsView(generics.RetrieveAPIView):
    queryset = Pool.objects.none()
    serializer_class = serializers.ProjectLimitsSerializer

    @swagger_auto_schema(tags=['cloud'])
    def get(self, request, *args, **kwargs):
        """
        Get Absolute limits of OpenStack project.
        """
        project_limits = projects.get_project_limits()
        return Response(self.serializer_class(project_limits).data)
