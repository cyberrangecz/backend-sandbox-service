import structlog
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter
from rest_framework import generics
from rest_framework.views import APIView

from crczp.sandbox_ansible_app import serializers
from crczp.sandbox_common_lib import log_output_mixin
from crczp.sandbox_instance_app.models import AllocationRequest, CleanupRequest

LOG = structlog.get_logger()

COMMON_RESPONSE_PATTERNS = {
    401: OpenApiResponse(description='Unauthorized'),
    403: OpenApiResponse(description='Forbidden'),
    404: OpenApiResponse(description='Not Found'),
    500: OpenApiResponse(description='Internal Server Error')
}

@extend_schema(
    methods=["GET"],
    responses={200: serializers.NetworkingAnsibleAllocationStageSerializer(many=True),
               **COMMON_RESPONSE_PATTERNS}
)
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


@extend_schema(
    methods=["GET"],
    responses={200: serializers.UserAnsibleAllocationStageSerializer(many=True),
               **COMMON_RESPONSE_PATTERNS}
)
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


@extend_schema(
    methods=["GET"],
    responses={200: serializers.NetworkingAnsibleCleanupStageSerializer(many=True),
               **COMMON_RESPONSE_PATTERNS}
)
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


@extend_schema(
    methods=["GET"],
    responses={200: serializers.UserAnsibleCleanupStageSerializer(many=True),
               **COMMON_RESPONSE_PATTERNS}
)
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


@extend_schema(
    methods=["GET"],
    parameters=[
        OpenApiParameter(
            name='from_row',
            type=int,
            location=OpenApiParameter.QUERY,
            description='Row index (DB relative), used for incremental fetch',
            required=False
        )
    ],
    responses={
        200: OpenApiResponse(
            description="Networking Ansible Outputs with trimmed content and row count"
        ),
        **COMMON_RESPONSE_PATTERNS
    }
)
class NetworkingAnsibleOutputListView(log_output_mixin.CompressedOutputMixin, APIView):
    """
    get: Retrieve Ansible Outputs with trimmed content.
    """
    queryset = AllocationRequest.objects.all()

    def get(self, request, request_id):
        from_row = request.query_params.get('from_row', 0)
        try:
            from_row = int(from_row)
        except (ValueError, TypeError):
            from_row = 0

        allocation_request = get_object_or_404(AllocationRequest, pk=request_id)
        outputs_queryset = allocation_request.networkingansibleallocationstage.outputs

        return self.create_outputs_response(outputs_queryset, from_row)


@extend_schema(
    methods=["GET"],
    parameters=[
        OpenApiParameter(
            name='from_row',
            type=int,
            location=OpenApiParameter.QUERY,
            description='Row index (DB relative), used for incremental fetch',
            required=False
        )
    ],
    responses={
        200: OpenApiResponse(
            description="User Ansible Outputs with trimmed content and row count"
        ),
        **COMMON_RESPONSE_PATTERNS
    }
)
class UserAnsibleOutputListView(log_output_mixin.CompressedOutputMixin, APIView):
    """
    get: Retrieve Ansible Outputs with trimmed content.
    """
    queryset = AllocationRequest.objects.all()

    def get(self, request, request_id):
        from_row = request.query_params.get('from_row', 0)
        try:
            from_row = int(from_row)
        except (ValueError, TypeError):
            from_row = 0

        allocation_request = get_object_or_404(AllocationRequest, pk=request_id)
        outputs_queryset = allocation_request.useransibleallocationstage.outputs

        return self.create_outputs_response(outputs_queryset, from_row)
