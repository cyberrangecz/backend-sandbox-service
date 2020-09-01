import structlog
from kypo.sandbox_common_lib import utils
from kypo.sandbox_common_lib.pagination import PageNumberWithPageSizePagination
from kypo.sandbox_cloud_app.lib import projects
from kypo.sandbox_cloud_app import serializers

from rest_framework import generics
from rest_framework.response import Response

from kypo.sandbox_instance_app.models import Pool

from drf_yasg.utils import swagger_auto_schema

LOG = structlog.get_logger()


@utils.add_error_responses_doc('get', [401, 403, 500])
class ProjectInfo(generics.GenericAPIView):
    # Exploitation of the Pool model permissions, Since the Cloud App does not have any models.
    queryset = Pool.objects.none()  # Required for DjangoModelPermissions

    # noinspection PyMethodMayBeStatic
    @swagger_auto_schema(tags=['cloud'])
    def get(self, request):
        """
        Get the quota set and name of project.
        """
        project_name = projects.get_project_name()
        quota_set = projects.get_quota_set()
        serialized_quota = serializers.QuotaSetSerializer(quota_set)
        return Response({'project_name': project_name, 'quotas': serialized_quota.data})


@utils.add_error_responses_doc('get', [401, 403, 500])
class ProjectImages(generics.GenericAPIView,
                    PageNumberWithPageSizePagination):
    queryset = Pool.objects.none()

    # noinspection PyMethodMayBeStatic
    @swagger_auto_schema(tags=['cloud'])
    def get(self, request):
        """
        Get list of images.
        """

        image_set = projects.list_images()
        serialized_image_set = serializers.ImageSerializer(image_set, many=True)

        page = self.paginate_queryset(serialized_image_set.data)
        if page is not None:
            return self.get_paginated_response(page)

        return Response({'image_set': serialized_image_set.data})
