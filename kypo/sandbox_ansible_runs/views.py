import structlog
from django.shortcuts import get_object_or_404
from rest_framework import generics

from . import serializers
from .models import AnsibleAllocationStage

# Create logger and configure logging
LOG = structlog.get_logger()


class AnsibleAllocationStageDetail(generics.RetrieveAPIView):
    """
    get: Retrieve an ansible stage.
    """
    serializer_class = serializers.AnsibleAllocationStageSerializer
    queryset = AnsibleAllocationStage.objects.all()
    lookup_url_kwarg = "stage_id"


class AnsibleCleanupStageDetail(generics.RetrieveAPIView):
    """
    get: Retrieve an ansible stage.
    """
    serializer_class = serializers.AnsibleCleanupStageSerializer
    queryset = AnsibleAllocationStage.objects.all()
    lookup_url_kwarg = "stage_id"


class AnsibleStageOutputList(generics.ListAPIView):
    serializer_class = serializers.AnsibleOutputSerializer

    def get_queryset(self):
        request_id = self.kwargs.get('stage_id')
        stage = get_object_or_404(AnsibleAllocationStage, pk=request_id)
        return stage.outputs.all()
