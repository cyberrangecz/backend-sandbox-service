import structlog
from django.shortcuts import get_object_or_404
from rest_framework import generics

from kypo.sandbox_ansible_app import serializers
from kypo.sandbox_ansible_app.models import AnsibleAllocationStage

from kypo.sandbox_common_lib import utils

LOG = structlog.get_logger()


@utils.add_error_responses_doc('get', [401, 403, 404, 500])
class AnsibleAllocationStageDetail(generics.RetrieveAPIView):
    """
    get: Retrieve an `ansible` Allocation stage.
    """
    serializer_class = serializers.AnsibleAllocationStageSerializer
    queryset = AnsibleAllocationStage.objects.all()
    lookup_url_kwarg = "stage_id"


@utils.add_error_responses_doc('get', [401, 403, 404, 500])
class AnsibleCleanupStageDetail(generics.RetrieveAPIView):
    """
    get: Retrieve an `ansible` Cleanup stage.
    """
    serializer_class = serializers.AnsibleCleanupStageSerializer
    queryset = AnsibleAllocationStage.objects.all()
    lookup_url_kwarg = "stage_id"


@utils.add_error_responses_doc('get', [401, 403, 404, 500])
class AnsibleStageOutputList(generics.ListAPIView):
    """
    get: Retrieve a list of Ansible Outputs.
    """
    serializer_class = serializers.AnsibleOutputSerializer

    def get_queryset(self):
        request_id = self.kwargs.get('stage_id')
        stage = get_object_or_404(AnsibleAllocationStage, pk=request_id)
        return stage.outputs.all()
