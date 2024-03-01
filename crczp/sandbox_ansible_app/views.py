import structlog
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from rest_framework import generics
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi

from crczp.sandbox_common_lib import utils
from crczp.sandbox_instance_app.models import AllocationRequest, CleanupRequest
from crczp.sandbox_ansible_app import serializers

LOG = structlog.get_logger()

COMMON_RESPONSE_PATTERNS = {
    401: openapi.Response('Unauthorized'),
    403: openapi.Response('Forbidden'),
    404: openapi.Response('Not Found'),
    500: openapi.Response('Internal Server Error')
}


@method_decorator(name='get', decorator=swagger_auto_schema(
    responses={200: serializers.NetworkingAnsibleAllocationStageSerializer(many=True),
               **COMMON_RESPONSE_PATTERNS}
))
class NetworkingAnsibleAllocationStageDetailView(generics.RetrieveAPIView):
    """
    get: Retrieve a `Networking Ansible` Allocation stage.
    """
    serializer_class = serializers.NetworkingAnsibleAllocationStageSerializer
    queryset = AllocationRequest.objects.all()
    lookup_url_kwarg = 'request_id'

    def get_object(self):
        request = super().get_object()
        return request.networkingansibleallocationstage


@method_decorator(name='get', decorator=swagger_auto_schema(
    responses={200: serializers.UserAnsibleAllocationStageSerializer(many=True),
               **COMMON_RESPONSE_PATTERNS}
))
class UserAnsibleAllocationStageDetailView(generics.RetrieveAPIView):
    """
    get: Retrieve a `User Ansible` Allocation stage.
    """
    serializer_class = serializers.UserAnsibleAllocationStageSerializer
    queryset = AllocationRequest.objects.all()
    lookup_url_kwarg = 'request_id'

    def get_object(self):
        request = super().get_object()
        return request.useransibleallocationstage


@method_decorator(name='get', decorator=swagger_auto_schema(
    responses={200: serializers.NetworkingAnsibleCleanupStageSerializer(many=True),
               **COMMON_RESPONSE_PATTERNS}
))
class NetworkingAnsibleCleanupStageDetailView(generics.RetrieveAPIView):
    """
    get: Retrieve a `Networking Ansible` Cleanup stage.
    """
    serializer_class = serializers.NetworkingAnsibleCleanupStageSerializer
    queryset = CleanupRequest.objects.all()
    lookup_url_kwarg = 'request_id'

    def get_object(self):
        request = super().get_object()
        return request.networkingansiblecleanupstage


@method_decorator(name='get', decorator=swagger_auto_schema(
    responses={200: serializers.UserAnsibleCleanupStageSerializer(many=True),
               **COMMON_RESPONSE_PATTERNS}
))
class UserAnsibleCleanupStageDetailView(generics.RetrieveAPIView):
    """
    get: Retrieve a `User Ansible` Cleanup stage.
    """
    serializer_class = serializers.UserAnsibleCleanupStageSerializer
    queryset = CleanupRequest.objects.all()
    lookup_url_kwarg = 'request_id'

    def get_object(self):
        request = super().get_object()
        return request.useransiblecleanupstage


@method_decorator(name='get', decorator=swagger_auto_schema(
    responses={200: serializers.AllocationAnsibleOutputSerializer(many=True),
               **COMMON_RESPONSE_PATTERNS}
))
class NetworkingAnsibleOutputListView(generics.ListAPIView):
    """
    get: Retrieve a list of Ansible Outputs.
    """
    serializer_class = serializers.AllocationAnsibleOutputSerializer

    def get_queryset(self):
        request_id = self.kwargs.get('request_id')
        request = get_object_or_404(AllocationRequest, pk=request_id)
        return request.networkingansibleallocationstage.outputs.all()


@method_decorator(name='get', decorator=swagger_auto_schema(
    responses={200: serializers.AllocationAnsibleOutputSerializer(many=True),
               **COMMON_RESPONSE_PATTERNS}
))
class UserAnsibleOutputListView(generics.ListAPIView):
    """
    get: Retrieve a list of Ansible Outputs.
    """
    serializer_class = serializers.AllocationAnsibleOutputSerializer

    def get_queryset(self):
        request_id = self.kwargs.get('request_id')
        request = get_object_or_404(AllocationRequest, pk=request_id)
        return request.useransibleallocationstage.outputs.all()
