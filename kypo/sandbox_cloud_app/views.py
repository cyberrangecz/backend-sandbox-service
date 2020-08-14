from kypo.sandbox_common_lib import utils
from kypo.sandbox_cloud_app.lib import projects
from kypo.sandbox_cloud_app import serializers

from rest_framework import generics
from rest_framework.response import Response


@utils.add_error_responses_doc('get', [401, 403, 500])
class ProjectQuotaSet(generics.GenericAPIView):

    def get(self, request):
        """
        Get the quota set of project.
        """
        quota_set = projects.get_quota_set()
        serialized_quota = serializers.QuotaSetSerializer(quota_set)
        return Response(serialized_quota.data)
