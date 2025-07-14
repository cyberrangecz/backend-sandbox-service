import datetime
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter, OpenApiTypes

import structlog
from crczp.sandbox_common_lib import utils
from crczp.sandbox_cloud_app.lib import projects
from crczp.sandbox_cloud_app import serializers

from rest_framework import generics
from rest_framework.response import Response

from crczp.sandbox_common_lib.common_cloud import list_images
from crczp.sandbox_instance_app.models import Pool

LOG = structlog.get_logger()


class ProjectInfoView(generics.RetrieveAPIView):
    # Exploitation of the Pool model permissions, Since the Cloud App does not have any models.
    queryset = Pool.objects.none()  # Required for DjangoModelPermissions
    serializer_class = serializers.QuotaSetSerializer

    # noinspection PyMethodMayBeStatic
    @extend_schema(
        tags=['cloud'],
        responses={
            200: OpenApiResponse(
                response=serializers.QuotaSetSerializer,
                description='Project name and quotas'
            ),
            **{k: v for k, v in utils.ERROR_RESPONSES.items() if k in [401, 403, 500]}
        }
    )
    def get(self, request, *args, **kwargs):
        """
        Get the quota set and name of project.
        """
        project_name = projects.get_project_name()
        quota_set = projects.get_quota_set()
        serialized_quota = serializers.QuotaSetSerializer(quota_set)
        return Response({'project_name': project_name, 'quotas': serialized_quota.data})


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

    @extend_schema(
        tags=['cloud'],
        parameters=[
            OpenApiParameter(name='name', location=OpenApiParameter.QUERY, type=OpenApiTypes.STR),
            OpenApiParameter(name='os_distro', location=OpenApiParameter.QUERY, type=OpenApiTypes.STR),
            OpenApiParameter(name='os_type', location=OpenApiParameter.QUERY, type=OpenApiTypes.STR),
            OpenApiParameter(name='visibility', location=OpenApiParameter.QUERY, type=OpenApiTypes.STR),
            OpenApiParameter(name='default_user', location=OpenApiParameter.QUERY, type=OpenApiTypes.STR),
            OpenApiParameter(
                name='onlyCustom',
                location=OpenApiParameter.QUERY,
                type=OpenApiTypes.BOOL,
                description='Returns only images with the attribute '
                            'owner_specified.openstack.created_by set to onlyCustom',
                default=False
            ),
            OpenApiParameter(
                name='GUI',
                location=OpenApiParameter.QUERY,
                type=OpenApiTypes.BOOL,
                description='Returns only images with the attribute '
                            'owner_specified.openstack.gui_access set to true',
                default=False
            ),
            OpenApiParameter(
                name='cached',
                location=OpenApiParameter.QUERY,
                type=OpenApiTypes.BOOL,
                description='Performs the faster version of this endpoint.',
                default=False
            ),
        ],
        responses={
            200: OpenApiResponse(
                response=serializers.ImageSerializer(many=True),
                description='List of images'
            ),
            **{k: v for k, v in utils.ERROR_RESPONSES.items() if k in [401, 403, 500]}
        }
    )
    def get(self, request, *args, **kwargs):
        """
        Get list of images.
        """
        cached_request = request.GET.get('cached', 'false').lower() == 'true'
        image_set = list_images(cached=cached_request)

        if request.GET.get('onlyCustom') == "true":
            image_set = [image for image in image_set if
                         image.owner_specified.get('owner_specified.openstack.custom', 'other')
                         == 'true']
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


class ProjectLimitsView(generics.RetrieveAPIView):
    queryset = Pool.objects.none()
    serializer_class = serializers.ProjectLimitsSerializer

    @extend_schema(
        tags=['cloud'],
        responses={
            200: OpenApiResponse(
                response=serializers.ProjectLimitsSerializer,
                description='Absolute limits of OpenStack project'
            ),
            **{k: v for k, v in utils.ERROR_RESPONSES.items() if k in [401, 403, 500]}
        }
    )

    def get(self, request, *args, **kwargs):
        """
        Get Absolute limits of OpenStack project.
        """
        project_limits = projects.get_project_limits()
        return Response(self.serializer_class(project_limits).data)
