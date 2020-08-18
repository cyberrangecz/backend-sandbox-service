from kypo.sandbox_common_lib import utils
from kypo.sandbox_cloud_app.lib import projects
from kypo.sandbox_cloud_app import serializers

from rest_framework import generics
from rest_framework.response import Response


@utils.add_error_responses_doc('get', [401, 403, 500])
class ProjectInfo(generics.GenericAPIView):

    def get(self, request):
        """
        Get the quota set and name of project.
        """
        project_name = projects.get_project_name()
        quota_set = projects.get_quota_set()
        serialized_quota = serializers.QuotaSetSerializer(quota_set)
        return Response({'project_name': project_name, 'quotas': serialized_quota.data})
