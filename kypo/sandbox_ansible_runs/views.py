import structlog
from django.http import StreamingHttpResponse
from rest_framework import generics

from . import ansible_service, serializers
from .models import AnsibleAllocationStage

# Create logger and configure logging
LOG = structlog.get_logger()


class AnsibleStageDetail(generics.RetrieveAPIView):
    """
    get: Retrieve an ansible stage.
    """
    serializer_class = serializers.AnsibleAllocationStageSerializer
    queryset = AnsibleAllocationStage.objects.all()
    lookup_url_kwarg = "stage_id"


class AnsibleStageOutputList(generics.GenericAPIView):
    """Class for managing Ansible outputs"""
    queryset = AnsibleAllocationStage.objects.all()
    serializer_class = serializers.AnsibleOutputSerializer
    lookup_url_kwarg = "stage_id"
    pagination_class = None

    # noinspection PyUnusedLocal
    def get(self, request, stage_id):
        """Retrieve Ansible output and return it as a _Streaming response_."""
        ansible_run = self.get_object()
        generator = ansible_service.asseble_output(ansible_run)
        return StreamingHttpResponse(generator)
