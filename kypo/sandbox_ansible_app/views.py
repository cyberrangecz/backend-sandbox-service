import structlog
from django.shortcuts import get_object_or_404
from rest_framework import generics

from kypo.sandbox_common_lib import utils
from kypo.sandbox_instance_app.models import AllocationRequest, CleanupRequest
from kypo.sandbox_ansible_app import serializers

LOG = structlog.get_logger()


@utils.add_error_responses_doc('get', [401, 403, 404, 500])
class NetworkingAnsibleAllocationStageDetail(generics.RetrieveAPIView):
    """
    get: Retrieve a `Networking Ansible` Allocation stage.
    """
    serializer_class = serializers.NetworkingAnsibleAllocationStageSerializer
    queryset = AllocationRequest.objects.all()
    lookup_url_kwarg = 'request_id'

    def get_object(self):
        request = super().get_object()
        return request.networkingansibleallocationstage


@utils.add_error_responses_doc('get', [401, 403, 404, 500])
class UserAnsibleAllocationStageDetail(generics.RetrieveAPIView):
    """
    get: Retrieve a `User Ansible` Allocation stage.
    """
    serializer_class = serializers.UserAnsibleAllocationStageSerializer
    queryset = AllocationRequest.objects.all()
    lookup_url_kwarg = 'request_id'

    def get_object(self):
        request = super().get_object()
        return request.useransibleallocationstage


@utils.add_error_responses_doc('get', [401, 403, 404, 500])
class NetworkingAnsibleCleanupStageDetail(generics.RetrieveAPIView):
    """
    get: Retrieve a `Networking Ansible` Cleanup stage.
    """
    serializer_class = serializers.NetworkingAnsibleCleanupStageSerializer
    queryset = CleanupRequest.objects.all()
    lookup_url_kwarg = 'request_id'

    def get_object(self):
        request = super().get_object()
        return request.networkingansiblecleanupstage


@utils.add_error_responses_doc('get', [401, 403, 404, 500])
class UserAnsibleCleanupStageDetail(generics.RetrieveAPIView):
    """
    get: Retrieve a `User Ansible` Cleanup stage.
    """
    serializer_class = serializers.UserAnsibleCleanupStageSerializer
    queryset = CleanupRequest.objects.all()
    lookup_url_kwarg = 'request_id'

    def get_object(self):
        request = super().get_object()
        return request.useransiblecleanupstage


@utils.add_error_responses_doc('get', [401, 403, 404, 500])
class NetworkingAnsibleOutputList(generics.ListAPIView):
    """
    get: Retrieve a list of Ansible Outputs.
    """
    serializer_class = serializers.AllocationAnsibleOutputSerializer

    def get_queryset(self):
        request_id = self.kwargs.get('request_id')
        request = get_object_or_404(AllocationRequest, pk=request_id)
        return request.networkingansibleallocationstage.outputs.all()


@utils.add_error_responses_doc('get', [401, 403, 404, 500])
class UserAnsibleOutputList(generics.ListAPIView):
    """
    get: Retrieve a list of Ansible Outputs.
    """
    serializer_class = serializers.AllocationAnsibleOutputSerializer

    def get_queryset(self):
        request_id = self.kwargs.get('request_id')
        request = get_object_or_404(AllocationRequest, pk=request_id)
        return request.useransibleallocationstage.outputs.all()
