from wsgiref.util import FileWrapper

import structlog
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse, Http404
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiRequest, OpenApiParameter
from rest_framework import status, generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from crczp.sandbox_common_lib import exceptions, utils, log_output_mixin
from crczp.sandbox_common_lib.pagination import PageNumberWithPageSizePagination


class PoolAllocationUnitPagination(PageNumberWithPageSizePagination):
    """Pagination for pool sandbox-allocation-units list. Maps frontend sort param to model field."""
    sort_field_mapping = {'allocation_unit_id': 'id'}
from crczp.sandbox_common_lib.swagger_typing import SandboxDefinitionSerializer, \
    PoolRequestSerializer, PoolResponseSerializer
from crczp.sandbox_common_lib.utils import get_object_or_404
from crczp.sandbox_definition_app.lib import definitions
from crczp.sandbox_definition_app.serializers import DefinitionSerializer
from crczp.sandbox_instance_app import serializers
from crczp.sandbox_instance_app.lib import pools, sandboxes, nodes, \
    requests as sandbox_requests
from crczp.sandbox_instance_app.lib import stage_handlers
from crczp.sandbox_instance_app.models import Pool, Sandbox, SandboxAllocationUnit, \
    AllocationRequest, CleanupRequest, SandboxLock, PoolLock
from crczp.sandbox_uag.permissions import (
    AdminPermission,
    CreateAllocationUnitForSelfOrOrganizerAdminPermission,
    CreateCleanupRequestForSelfOrOrganizerAdminPermission,
    ListAllocationUnitsByCreatorForSelfOrOrganizerAdminPermission,
    OrganizerPermission,
    RetrieveAllocationUnitForSelfOrOrganizerAdminPermission,
    RetrieveSandboxForSelfOrOrganizerAdminPermission,
)

LOG = structlog.get_logger()

COMMON_RESPONSE_PATTERNS = {
    401: OpenApiResponse(description='Unauthorized'),
    403: OpenApiResponse(description='Forbidden'),
    404: OpenApiResponse(description='Not Found'),
    500: OpenApiResponse(description='Internal Server Error')
}

POOL_RESPONSES = {**COMMON_RESPONSE_PATTERNS, 400: OpenApiResponse(description='Bad Request')}
SANDBOX_RESPONSES = {**COMMON_RESPONSE_PATTERNS}


@extend_schema(
    methods=["GET"],
    responses={
        200: OpenApiResponse(
            response=serializers.PoolSerializer(many=True),
            description="List of Pools"
        ),
        **{k: v for k, v in utils.ERROR_RESPONSES.items() if k in [401, 403, 500]}
    }
)
class PoolListCreateView(generics.ListCreateAPIView):
    """
    get: Get a list of pools.
    """
    queryset = Pool.objects.all()
    serializer_class = serializers.PoolSerializer

    @extend_schema(
        request=OpenApiRequest(PoolRequestSerializer),
        responses={
            201: OpenApiResponse(response=PoolResponseSerializer, description="Pool created"),
            **POOL_RESPONSES
        }
    )
    def post(self, request, *args, **kwargs):
        """Creates new pool.
        Also creates a new key-pair and certificate, which is then passed to terraform client.
        The key is then used as management key for this pool, which means that the management
         key-pair is the same for each sandbox in the pool.
        """
        created_by = None if isinstance(request.user, AnonymousUser) else request.user
        pool = pools.create_pool(request.data, created_by)
        serializer = self.serializer_class(pool)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


@extend_schema(
    methods=["GET"],
    responses={
        200: PoolResponseSerializer,
        **POOL_RESPONSES
    }
)
class PoolDetailDeleteUpdateView(generics.RetrieveDestroyAPIView):
    """
    get: Retrieve a pool.
    """
    queryset = Pool.objects.all()
    serializer_class = serializers.PoolSerializer
    lookup_url_kwarg = "pool_id"

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="force",
                type=bool,
                location=OpenApiParameter.QUERY,
                description="Force the deletion of sandboxes",
                required=False,
                default=False
            ),
        ],
        responses={**POOL_RESPONSES}
    )
    def delete(self, request, *args, **kwargs):
        """
        Delete pool. The pool must be empty.
        First delete all sandboxes in given Pool.
        """
        pool = self.get_object()
        force = request.GET.get('force', 'false') == 'true'

        if force and pool.size > 0:
            pool_units = SandboxAllocationUnit.objects.filter(pool_id=pool.id)
            sandbox_requests.create_cleanup_requests(pool_units, force, delete_pool=True)
            return Response(status=status.HTTP_201_CREATED)

        pools.delete_pool(pool)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        request=serializers.PoolSerializer,
        responses={
            200: serializers.PoolSerializer,
            **POOL_RESPONSES
        }
    )
    def patch(self, request, *args, **kwargs):
        pool = self.get_object()
        serializer = self.serializer_class(pool, data=request.data, partial=True)

        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(
    methods=["GET"],
    responses={
        200: SandboxDefinitionSerializer,
        **SANDBOX_RESPONSES
    }
)
class PoolDefinitionView(generics.RetrieveAPIView):
    """
    get: Retrieve the definition associated with a pool.
    """
    queryset = Pool.objects.all()
    lookup_url_kwarg = "pool_id"
    serializer_class = DefinitionSerializer

    def get_object(self):
        return super().get_object().definition


@extend_schema(
    methods=["GET"],
    responses={
        200: OpenApiResponse(
            response=serializers.PoolLockSerializer(many=True),
            description="List of Pool Locks"
        ),
        **SANDBOX_RESPONSES
    }
)
@extend_schema(
    methods=["POST"],
    request=OpenApiRequest(PoolRequestSerializer),
    responses={
        201: OpenApiResponse(response=PoolResponseSerializer, description="Pool created"),
        **POOL_RESPONSES
    }
)
class PoolLockListCreateView(generics.ListCreateAPIView):
    serializer_class = serializers.PoolLockSerializer
    """
    get: List locks for given pool.
    """

    def get_queryset(self):
        pool_id = self.kwargs.get('pool_id')
        get_object_or_404(Pool, pk=pool_id)
        return PoolLock.objects.filter(pool=pool_id)

    def post(self, request, *args, **kwargs):
        """Lock given pool."""
        pool = pools.get_pool(kwargs.get('pool_id'))
        training_access_token = request.data.get('training_access_token', None)
        lock = pools.lock_pool(pool, training_access_token)
        return Response(self.serializer_class(lock).data, status=status.HTTP_201_CREATED)


@extend_schema(
    methods=["GET"],
    responses={
        200: OpenApiResponse(response=serializers.PoolLockSerializer),
        **SANDBOX_RESPONSES
    }
)
@extend_schema(
    methods=["DELETE"],
    responses={
        204: OpenApiResponse(description="No Content"),
        **SANDBOX_RESPONSES
    }
)
class PoolLockDetailDeleteView(generics.RetrieveDestroyAPIView):
    """
    get: Retrieve details about given lock.
    delete: Delete given lock.
    """
    queryset = PoolLock.objects.all()
    lookup_url_kwarg = "lock_id"
    serializer_class = serializers.PoolLockSerializer


@extend_schema(
    methods=["GET"],
    responses={
        200: OpenApiResponse(
            response=serializers.AllocationRequestSerializer(many=True),
            description="List of Allocation Requests"
        ),
        **SANDBOX_RESPONSES
    }
)
class PoolAllocationRequestListView(generics.ListAPIView):
    """
    get: List Allocation Request for this pool.
    """
    serializer_class = serializers.AllocationRequestSerializer

    def get_queryset(self):
        pool_id = self.kwargs.get('pool_id')
        pool = get_object_or_404(Pool, pk=pool_id)
        return AllocationRequest.objects.filter(allocation_unit__in=pool.allocation_units.all())


@extend_schema(
    methods=["GET"],
    responses={
        200: OpenApiResponse(
            response=serializers.CleanupRequestSerializer(many=True),
            description="List of Cleanup Requests"
        ),
        **SANDBOX_RESPONSES
    }
)
@extend_schema(
    methods=["POST"],
    parameters=[
        OpenApiParameter(
            name="force",
            type=bool,
            location=OpenApiParameter.QUERY,
            description="Force the deletion of sandboxes",
            required=False
        )
    ],
    responses={
        201: OpenApiResponse(
            response=serializers.CleanupRequestSerializer,
            description="Cleanup Request created"
        ),
        **POOL_RESPONSES
    }
)
class PoolCleanupRequestsListCreateView(generics.ListCreateAPIView):
    """
    get: List Cleanup Requests for this pool.
    """
    serializer_class = serializers.CleanupRequestSerializer

    def get_queryset(self):
        pool_id = self.kwargs.get('pool_id')
        get_object_or_404(Pool, pk=pool_id)
        return CleanupRequest.objects.filter(allocation_unit__pool_id=pool_id)

    def post(self, request, *args, **kwargs):
        """Deletes all sandboxes in the pool. With an optional parameter *force*,
        it forces the deletion."""
        pool_id = kwargs.get('pool_id')
        get_object_or_404(Pool, pk=pool_id)
        pool_units = SandboxAllocationUnit.objects.filter(pool_id=pool_id)
        force = request.GET.get('force', 'false') == 'true'
        sandbox_requests.create_cleanup_requests(pool_units, force)
        return Response(status=status.HTTP_201_CREATED)

class PoolCleanupRequestUnlockedCreateView(APIView):
    serializer_class = serializers.PoolCleanupRequestSerializer
    queryset = CleanupRequest.objects.none()

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name='force',
                type=bool,
                location=OpenApiParameter.QUERY,
                description="Force the deletion of sandboxes",
                required=False
            )
        ]
    )
    def post(self, request, *args, **kwargs):
        """Deletes all unlocked sandboxes in a pool. With an optional parameter *force*, it forces
         the deletion."""
        pool_id = kwargs.get('pool_id')
        get_object_or_404(Pool, pk=pool_id)
        pool_units = SandboxAllocationUnit.objects.filter(pool_id=pool_id)
        pool_units = [unit for unit in pool_units if hasattr(unit, 'sandbox') and
                      not hasattr(unit.sandbox, "lock")]
        force = request.GET.get('force', 'false') == 'true'
        sandbox_requests.create_cleanup_requests(pool_units, force)
        return Response(status=status.HTTP_201_CREATED)


class PoolCleanupRequestFailedCreateView(APIView):
    serializer_class = serializers.PoolCleanupRequestFailedSerializer
    queryset = CleanupRequest.objects.none()

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name='force',
                type=bool,
                location=OpenApiParameter.QUERY,
                description="Force the deletion of sandboxes",
                required=False
            )
        ],
        responses={
            201: OpenApiResponse(description="Cleanup Request created")
        }
    )
    def post(self, request, *args, **kwargs):
        """Deletes all failed sandboxes in a pool. With an optional parameter *force*, it forces
         the deletion."""
        pool_id = kwargs.get('pool_id')
        get_object_or_404(Pool, pk=pool_id)
        pool_units = SandboxAllocationUnit.objects.filter(pool_id=pool_id)
        force = request.GET.get('force', 'false') == 'true'
        pool_units = [unit for unit in pool_units if unit.allocation_request.stages.filter(failed=True).count()]
        sandbox_requests.create_cleanup_requests(pool_units, force)
        return Response(status=status.HTTP_201_CREATED)


@extend_schema(
    methods=["POST"],
    responses={
        200: OpenApiResponse(
            description="Number of queued allocation units cancelled",
            response=dict
        ),
        **POOL_RESPONSES
    }
)
class PoolCancelQueuedCreateView(APIView):
    """
    post: Cancel all allocation units in the pool that are still IN_QUEUE (no stage started).
    Leaves deploying or built sandboxes untouched. Returns cancelled_count.
    """
    permission_classes = [OrganizerPermission | AdminPermission]

    def post(self, request, *args, **kwargs):
        pool_id = kwargs.get('pool_id')
        get_object_or_404(Pool, pk=pool_id)
        cancelled = sandbox_requests.cancel_queued_allocation_units_in_pool(pool_id)
        return Response({'cancelled_count': cancelled}, status=status.HTTP_200_OK)


@extend_schema(
    methods=["POST"],
    responses={
        200: OpenApiResponse(
            description="Number of stuck allocation units force-cancelled",
            response=dict
        ),
        **POOL_RESPONSES
    }
)
class PoolForceCancelAllocationCreateView(APIView):
    """
    post: Force-cancel all allocation units in the pool whose first stage has started
    but is not finished/failed (stuck jobs). Removes them from the Cyber Range DB only;
    OpenStack resources must be cleaned up manually. Returns force_cancelled_count.
    """
    permission_classes = [OrganizerPermission | AdminPermission]

    def post(self, request, *args, **kwargs):
        pool_id = kwargs.get('pool_id')
        get_object_or_404(Pool, pk=pool_id)
        cancelled = sandbox_requests.force_cancel_allocation_units_in_pool(pool_id)
        return Response({'force_cancelled_count': cancelled}, status=status.HTTP_200_OK)


@extend_schema(
    methods=["POST"],
    responses={
        200: OpenApiResponse(
            description="Number of stuck cleanup units force-removed",
            response=dict
        ),
        **POOL_RESPONSES
    }
)
class PoolForceCleanupCreateView(APIView):
    """
    post: Force-remove all allocation units in the pool that have a cleanup request
    that is not finished (cleanup running or stuck). Removes them from the Cyber Range
    DB only; cancel cleanup RQ jobs and delete records. Returns force_cleaned_count.
    """
    permission_classes = [OrganizerPermission | AdminPermission]

    def post(self, request, *args, **kwargs):
        pool_id = kwargs.get('pool_id')
        get_object_or_404(Pool, pk=pool_id)
        cleaned = sandbox_requests.force_cleanup_units_in_pool(pool_id)
        return Response({'force_cleaned_count': cleaned}, status=status.HTTP_200_OK)


def _is_allocation_unit_active(unit: SandboxAllocationUnit) -> bool:
    """
    Consider an allocation unit active when it is not in a finished cleanup state
    and allocation stages are not failed (per single-sandbox-per-user spec).
    """
    try:
        cleanup = getattr(unit, 'cleanup_request', None)
        if cleanup is not None and cleanup.is_finished:
            return False
    except (AttributeError, Exception):
        pass
    try:
        alloc = getattr(unit, 'allocation_request', None)
        if alloc is not None and alloc.stages.filter(failed=True).exists():
            return False
    except (AttributeError, Exception):
        pass
    return True


@extend_schema(
    parameters=[
        OpenApiParameter(
            name='created_by_sub',
            type=str,
            location=OpenApiParameter.QUERY,
            description='OIDC sub of the creator (required for by-creator listing).',
            required=True
        ),
        OpenApiParameter(
            name='state',
            type=str,
            location=OpenApiParameter.QUERY,
            description='Filter by state: ACTIVE returns only units not in finished cleanup and without failed allocation.',
            required=False
        ),
    ],
    responses={
        200: OpenApiResponse(
            response=serializers.SandboxAllocationUnitSerializer(many=True),
            description='List of Sandbox Allocation Units by creator'
        ),
        **SANDBOX_RESPONSES
    }
)
class SandboxAllocationUnitByCreatorListView(generics.ListAPIView):
    """
    get: List sandbox allocation units by creator (created_by_sub).
    Trainees may list only their own (created_by_sub == JWT sub); Organizer/Admin may list any.
    """
    serializer_class = serializers.SandboxAllocationUnitSerializer
    permission_classes = [IsAuthenticated, ListAllocationUnitsByCreatorForSelfOrOrganizerAdminPermission]
    pagination_class = None  # Return plain list for service-to-service calls

    def get_queryset(self):
        created_by_sub = self.request.query_params.get('created_by_sub')
        if not created_by_sub:
            return SandboxAllocationUnit.objects.none()
        qs = SandboxAllocationUnit.objects.filter(created_by_sub=created_by_sub.strip())
        state = (self.request.query_params.get('state') or '').strip().upper()
        if state == 'ACTIVE':
            # Filter to active only (QuerySet for pagination)
            qs = qs.select_related(
                'pool', 'allocation_request', 'cleanup_request'
            ).prefetch_related('allocation_request__stages', 'cleanup_request__stages')
            active_ids = [u.id for u in qs if _is_allocation_unit_active(u)]
            return SandboxAllocationUnit.objects.filter(id__in=active_ids)
        return qs


@extend_schema(
    parameters=[
        OpenApiParameter(
            name='created_before',
            type=str,
            location=OpenApiParameter.QUERY,
            description='ISO8601 timestamp; return units with created_at < this (for cleanup job).',
            required=True
        ),
        OpenApiParameter(
            name='state',
            type=str,
            location=OpenApiParameter.QUERY,
            description='Filter: ACTIVE = not in finished cleanup, allocation not failed.',
            required=False
        ),
    ],
    responses={
        200: OpenApiResponse(
            response=serializers.SandboxAllocationUnitSerializer(many=True),
            description='List of Sandbox Allocation Units by age'
        ),
        **SANDBOX_RESPONSES
    }
)
class SandboxAllocationUnitByAgeListView(generics.ListAPIView):
    """
    get: List sandbox allocation units with created_at before given timestamp.
    For cleanup job; use state=ACTIVE to get only active units. Returns created_by_sub.
    """
    serializer_class = serializers.SandboxAllocationUnitSerializer
    permission_classes = [AdminPermission]

    def get_queryset(self):
        from django.utils.dateparse import parse_datetime
        created_before = self.request.query_params.get('created_before')
        if not created_before:
            return SandboxAllocationUnit.objects.none()
        dt = parse_datetime(created_before)
        if dt is None:
            return SandboxAllocationUnit.objects.none()
        qs = SandboxAllocationUnit.objects.filter(created_at__lt=dt)
        state = (self.request.query_params.get('state') or '').strip().upper()
        if state == 'ACTIVE':
            qs = qs.select_related(
                'pool', 'allocation_request', 'cleanup_request'
            ).prefetch_related('allocation_request__stages', 'cleanup_request__stages')
            active_ids = [u.id for u in qs if _is_allocation_unit_active(u)]
            return SandboxAllocationUnit.objects.filter(id__in=active_ids)
        return qs


@extend_schema(
    responses={
        200: OpenApiResponse(
            response=serializers.SandboxAllocationUnitSerializer(many=True),
            description='List of Sandbox Allocation Units'
        ),
        **SANDBOX_RESPONSES
    }
)
class SandboxAllocationUnitListCreateView(generics.ListCreateAPIView):
    """
    get: List Sandbox Allocation Units in the pool. When page or page_size is in the request, returns
         paginated response (Pool Detail UI). When neither is present, returns plain list (training-service).
    post: Create allocation unit(s). Trainees may create only one, for themselves (created_by_sub == JWT sub).
    """
    serializer_class = serializers.SandboxAllocationUnitSerializer
    permission_classes = [IsAuthenticated, CreateAllocationUnitForSelfOrOrganizerAdminPermission]
    pagination_class = None  # Default: plain list for training-service

    def get_pagination_class(self):
        if self.request is not None and (
                self.request.query_params.get('page') is not None
                or self.request.query_params.get('page_size') is not None):
            return PoolAllocationUnitPagination
        return None

    def list(self, request, *args, **kwargs):
        # Use pagination when UI sends page/page_size (Pool Detail); plain list for training-service
        self.pagination_class = self.get_pagination_class()
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        return SandboxAllocationUnit.objects.filter(pool_id=self.kwargs.get('pool_id'))

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name='count',
                type=int,
                location=OpenApiParameter.QUERY,
                description="Sandbox count parameter",
                required=False
            )
        ],
        responses={
            status.HTTP_201_CREATED: OpenApiResponse(
                response=serializers.SandboxAllocationUnitSerializer(many=True),
                description="Created Sandbox Allocation Units"
            ),
            **POOL_RESPONSES
        }
    )
    def post(self, request, *args, **kwargs):
        """Create Sandbox Allocation Unit.
        For each Allocation Unit the Allocation Request is created in given pool.
        If count is not specified, builds *max_size - current size*.
        Query Parameters:
        - *count:* How many sandboxes to build. Optional (defaults to max_size - current size).
        Body (optional, for service-to-service e.g. training backend):
        - *created_by_sub:* OIDC sub of the trainee creating the sandbox (single-sandbox-per-user flow).
        """
        pool = pools.get_pool(kwargs.get('pool_id'))
        count = request.GET.get('count')
        if count is not None:
            try:
                count = int(count)
            except ValueError:
                raise exceptions.ValidationError("Invalid parameter count: %s" % count)

        created_by = None if isinstance(request.user, AnonymousUser) else request.user
        created_by_sub = None
        if hasattr(request, 'data') and isinstance(request.data, dict):
            created_by_sub = request.data.get('created_by_sub') or None
            if created_by_sub is not None and not isinstance(created_by_sub, str):
                created_by_sub = str(created_by_sub).strip() or None

        units = pools.create_sandboxes_in_pool(
            pool, created_by, count=count, created_by_sub=created_by_sub
        )
        serializer = self.serializer_class(units, many=True)
        # Return plain list (no pagination) so callers like training-service get List<...> directly.
        return Response(serializer.data, status=status.HTTP_201_CREATED)


@extend_schema(
    methods=["GET"],
    responses={
        200: OpenApiResponse(
            response=serializers.SandboxAllocationUnitSerializer(),
            description="Retrieve a Sandbox Allocation Unit"
        ),
        **SANDBOX_RESPONSES
    }
)
@extend_schema(
    methods=["PATCH"],
    request=serializers.SandboxAllocationUnitSerializer,
    responses={
        200: OpenApiResponse(
            response=serializers.SandboxAllocationUnitSerializer(),
            description="Updated Sandbox Allocation Unit"
        ),
        **POOL_RESPONSES
    }
)
class SandboxAllocationUnitDetailUpdateView(generics.RetrieveAPIView):
    """get: Retrieve a Sandbox Allocation Unit. Trainees may GET only their own (created_by_sub)."""
    serializer_class = serializers.SandboxAllocationUnitSerializer
    queryset = SandboxAllocationUnit.objects.all()
    lookup_url_kwarg = "unit_id"
    permission_classes = [IsAuthenticated, RetrieveAllocationUnitForSelfOrOrganizerAdminPermission]

    def patch(self, request, *args, **kwargs):
        allocation_unit = self.get_object()
        serializer = self.serializer_class(allocation_unit, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(
    methods=["GET"],
    responses={
        200: OpenApiResponse(
            response=serializers.AllocationRequestSerializer(),
            description="Retrieve Allocation Request"
        ),
        **SANDBOX_RESPONSES
    }
)
class SandboxAllocationRequestView(generics.RetrieveAPIView):
    """
    get: Retrieve a Sandbox Allocation Request for an Allocation Unit.
    Each Allocation Unit has exactly one Allocation Request.
    (There may occur a situation where it has none, then it returns 404.)
    """
    queryset = SandboxAllocationUnit.objects.all()
    lookup_url_kwarg = "unit_id"
    serializer_class = serializers.AllocationRequestSerializer

    def get_object(self):
        unit = super().get_object()
        try:
            return unit.allocation_request
        except AttributeError:
            raise Http404(f"The allocation unit (ID={unit.id}) has no allocation request.")


@extend_schema(
    methods=["GET"],
    responses={
        200: OpenApiResponse(
            response=serializers.AllocationRequestSerializer(),
            description="Retrieve Allocation Request"
        ),
        **SANDBOX_RESPONSES
    }
)
class AllocationRequestDetailView(generics.RetrieveAPIView):
    """get: Retrieve a Sandbox Allocation Request."""
    queryset = AllocationRequest.objects.all()
    serializer_class = serializers.AllocationRequestSerializer
    lookup_url_kwarg = 'request_id'


class AllocationRequestCancelView(generics.GenericAPIView):
    serializer_class = serializers.AllocationRequestSerializer
    queryset = AllocationRequest.objects.all()
    lookup_url_kwarg = "request_id"

    @extend_schema(
        responses={
            status.HTTP_200_OK: OpenApiResponse(description="Success, no content"),
            **POOL_RESPONSES
        }
    )
    def patch(self, request, *args, **kwargs):
        """Cancel given Allocation Request. Returns no data if OK (200)."""
        sandbox_requests.cancel_allocation_request(self.get_object())
        return Response()


@extend_schema(
    methods=["GET"],
    responses={
        200: OpenApiResponse(
            response=serializers.CleanupRequestSerializer(),
            description="Retrieve Cleanup Request"
        ),
        **SANDBOX_RESPONSES
    }
)
class SandboxCleanupRequestView(generics.RetrieveDestroyAPIView,
                                generics.CreateAPIView):
    queryset = SandboxAllocationUnit.objects.all()
    lookup_url_kwarg = "unit_id"
    serializer_class = serializers.CleanupRequestSerializer
    permission_classes = [IsAuthenticated, CreateCleanupRequestForSelfOrOrganizerAdminPermission]

    def get(self, request, *args, **kwargs):
        """Retrieve a Sandbox Cleanup Request for an Allocation Unit.
        Each Allocation Unit has at most one Cleanup Request.
        If it has none, then it returns 404.
        """
        unit = self.get_object()
        try:
            request = unit.cleanup_request
        except AttributeError:
            raise Http404(f"The allocation unit (ID={unit.id}) has no cleanup request.")
        serializer = self.get_serializer(request)
        return Response(serializer.data)

    @extend_schema(
        responses={
            201: serializers.CleanupRequestSerializer,
        }
    )
    def post(self, request, *args, **kwargs):
        """ Create cleanup request."""
        unit = self.get_object()
        force = request.GET.get('force', 'false') == 'true'
        sandbox_requests.create_cleanup_requests([unit], force)
        return Response(status=status.HTTP_201_CREATED)

    def delete(self, request, *args, **kwargs):
        """ Delete cleanup request. Must be finished or cancelled."""
        unit = self.get_object()
        sandbox_requests.delete_cleanup_request(unit.cleanup_request)
        return Response({}, status=status.HTTP_204_NO_CONTENT)


class SandboxAllocationStagesRestartView(generics.GenericAPIView):
    serializer_class = serializers.SandboxAllocationUnitSerializer
    queryset = SandboxAllocationUnit.objects.all()
    lookup_url_kwarg = "unit_id"

    @extend_schema(
        responses={
            status.HTTP_201_CREATED: serializers.SandboxAllocationUnitSerializer,
            **POOL_RESPONSES
        }
    )
    def patch(self, request, *args, **kwargs):
        """
        Restart all failed sandbox allocation stages.
        """
        allocation_unit = self.get_object()
        request = sandbox_requests.restart_allocation_stages(allocation_unit)

        serializer = self.serializer_class(request)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


@extend_schema(
    methods=["GET"],
    responses={
        200: OpenApiResponse(
            response=serializers.CleanupRequestSerializer,
            description="Retrieve Cleanup Request"
        ),
        **SANDBOX_RESPONSES
    }
)
class CleanupRequestDetailView(generics.RetrieveAPIView):
    """get: Retrieve a Sandbox Cleanup Request."""
    serializer_class = serializers.CleanupRequestSerializer
    queryset = CleanupRequest.objects.all()
    lookup_url_kwarg = "request_id"


class CleanupRequestCancelView(generics.GenericAPIView):
    serializer_class = serializers.CleanupRequestSerializer
    queryset = CleanupRequest.objects.all()
    lookup_url_kwarg = "request_id"

    @extend_schema(
        responses={
            status.HTTP_200_OK: OpenApiResponse(description="Success, no content"),
            **POOL_RESPONSES
        }
    )
    def patch(self, request, *args, **kwargs):
        """Cancel given Cleanup Request. Returns no data if OK (200)."""
        sandbox_requests.cancel_cleanup_request(self.get_object())
        return Response()


@extend_schema(
    methods=["GET"],
    responses={
        200: OpenApiResponse(
            response=serializers.AllocationTerraformOutputSerializer(many=True),
            description="List of Terraform Outputs"
        ),
        **SANDBOX_RESPONSES
    }
)
class TerraformAllocationStageDetailView(generics.RetrieveAPIView):
    """
    get: Retrieve an `openstack` allocation stage.
    Null `status` and `status_reason` attributes mean, that stack does not have them;
    AKA it does not exist in OpenStack.
    """
    serializer_class = serializers.TerraformAllocationStageSerializer
    queryset = AllocationRequest.objects.all()
    lookup_url_kwarg = "request_id"

    def get_object(self):
        request = super().get_object()
        return stage_handlers.AllocationStackStageHandler(request.stackallocationstage).stage


@extend_schema(
    methods=["GET"],
    responses={
        200: OpenApiResponse(
            response=serializers.TerraformCleanupStageSerializer,
            description="Retrieve Terraform Cleanup Stage"
        ),
        **SANDBOX_RESPONSES
    }
)
class TerraformCleanupStageDetailView(generics.RetrieveAPIView):
    """get: Retrieve an `openstack` Cleanup stage."""
    serializer_class = serializers.TerraformCleanupStageSerializer
    queryset = CleanupRequest.objects.all()
    lookup_url_kwarg = 'request_id'

    def get_object(self):
        request = super().get_object()
        return request.stackcleanupstage


@extend_schema(
    methods=["GET"],
    responses={
        200: OpenApiResponse(
            response=serializers.AllocationTerraformOutputSerializer(many=True),
            description="List of Terraform Outputs"
        ),
        **SANDBOX_RESPONSES
    }
)
class TerraformAllocationStageOutputListView(log_output_mixin.CompressedOutputMixin, APIView):
    queryset = AllocationRequest.objects.all()

    def get(self, request, request_id):
        from_row = request.query_params.get('from_row', 0)
        try:
            from_row = int(from_row)
        except (ValueError, TypeError):
            from_row = 0

        allocation_request = get_object_or_404(AllocationRequest, pk=request_id)
        outputs_queryset = allocation_request.stackallocationstage.terraform_outputs

        return self.create_outputs_response(outputs_queryset, from_row)


#########################################
# POOLS OF SANDBOXES MANIPULATION VIEWS #
#########################################

@extend_schema(
    methods=["GET"],
    responses={
        200: OpenApiResponse(
            response=serializers.SandboxSerializer(many=True),
            description="List of Sandboxes"
        ),
        **SANDBOX_RESPONSES
    }
)
class PoolSandboxListView(generics.ListAPIView):
    serializer_class = serializers.SandboxSerializer
    permission_classes = [OrganizerPermission | AdminPermission]

    def get_queryset(self):
        pool_id = self.kwargs.get('pool_id')
        pool = get_object_or_404(Pool, pk=pool_id)
        alloc_unit_ids = [unit.id for unit in pool.allocation_units.all()]
        return Sandbox.objects.filter(allocation_unit_id__in=alloc_unit_ids, ready=True)


class SandboxGetAndLockView(generics.RetrieveAPIView):
    serializer_class = serializers.SandboxSerializer
    queryset = Sandbox.objects.filter(ready=True)  # To allow trainee to access training run!
    lookup_url_kwarg = "pool_id"

    @extend_schema(
        responses={
            status.HTTP_409_CONFLICT: OpenApiResponse(
                description="No free sandboxes; all sandboxes are locked.",
                response=utils.ErrorSerilizer
            ),
            **SANDBOX_RESPONSES
        }
    )
    def get(self, request, *args, **kwargs):
        """
        Get unlocked sandbox in given pool and lock it.
        Return 409 if all are locked, 403 if training access token invalid or 400 if there is no lock.
        """
        pool_id = self.kwargs.get('pool_id')
        pool = get_object_or_404(Pool, id=pool_id)
        training_access_token = self.kwargs.get('training_access_token')

        if hasattr(pool, 'lock'):
            if pool.lock.training_access_token is None:
                return Response({'detail': 'This pool does not have a training assigned'},
                                status=status.HTTP_403_FORBIDDEN)
            elif pool.lock.training_access_token != training_access_token:
                return Response({'detail': 'Provided training access token is not valid.'},
                                status=status.HTTP_403_FORBIDDEN)
        else:
            return Response({'detail': 'The pool is not locked.'},
                            status=status.HTTP_400_BAD_REQUEST)

        created_by = None if isinstance(request.user, AnonymousUser) else request.user
        sandbox = pools.get_unlocked_sandbox(pool, created_by)
        if not sandbox:
            return Response({'detail': 'All sandboxes are already locked.'},
                            status=status.HTTP_409_CONFLICT)
        return Response(self.serializer_class(sandbox).data)


#######################################
# SANDBOX MANIPULATION VIEWS #
#######################################

@extend_schema(
    methods=["GET"],
    responses={
        200: OpenApiResponse(
            response=serializers.SandboxSerializer,
            description="Sandbox details"
        ),
        **SANDBOX_RESPONSES
    }
)
class SandboxDetailView(generics.RetrieveAPIView):
    """get: Retrieve a sandbox."""
    serializer_class = serializers.SandboxSerializer
    lookup_url_kwarg = "sandbox_uuid"
    queryset = Sandbox.objects.filter(ready=True)
    permission_classes = [IsAuthenticated, RetrieveSandboxForSelfOrOrganizerAdminPermission]


@extend_schema(
    methods=["GET"],
    responses={
        200: OpenApiResponse(response=serializers.SandboxLockSerializer, description="Sandbox Lock details"),
        **SANDBOX_RESPONSES
    }
)
@extend_schema(
    methods=["POST"],
    responses={
        201: OpenApiResponse(response=serializers.SandboxLockSerializer, description="Sandbox Lock created"),
        **SANDBOX_RESPONSES
    }
)
class SandboxAllocationUnitLockRetrieveCreateDestroyView(generics.RetrieveDestroyAPIView,
                                                         generics.CreateAPIView):
    """
    post: Create locks for given sandbox allocation unit if its sandbox exists.
    delete: Destroy locks for given sandbox allocation unit if its sandbox exists."""
    queryset = SandboxAllocationUnit.objects.all()
    lookup_url_kwarg = "unit_id"
    serializer_class = serializers.SandboxLockSerializer

    def get(self, request, *args, **kwargs):
        """get: Retrieve lock for given sandbox allocation unit if its sandbox exists."""
        allocation_unit = self.get_object()
        if not hasattr(allocation_unit, "sandbox"):
            raise Http404(f'Sandbox allocation unit {allocation_unit.id} has no sandbox.')
        sandbox_id = allocation_unit.sandbox.id
        lock = SandboxLock.objects.get(sandbox=sandbox_id)
        return Response(self.get_serializer(lock).data)

    def post(self, request, *args, **kwargs):
        """Lock sandbox of given sandbox allocation unit if the sandbox exists."""
        allocation_unit = self.get_object()
        if not hasattr(allocation_unit, "sandbox"):
            raise Http404(f'Sandbox allocation unit {allocation_unit.id} has no sandbox.')
        sandbox = allocation_unit.sandbox
        created_by = None if isinstance(request.user, AnonymousUser) else request.user
        lock = sandboxes.lock_sandbox(sandbox=sandbox, created_by=created_by)
        return Response(self.get_serializer(lock).data, status=status.HTTP_201_CREATED)

    def delete(self, request, *args, **kwargs):
        """Delete lock of given sandbox allocation unit if it has sandbox.
        If the sandbox has no lock (e.g. single-sandbox-per-user allocation), return 204 anyway (idempotent)."""
        allocation_unit = self.get_object()
        if not hasattr(allocation_unit, "sandbox"):
            raise Http404(f'Sandbox allocation unit {allocation_unit.id} has no sandbox.')
        sandbox = allocation_unit.sandbox
        if not hasattr(sandbox, "lock"):
            # No lock (e.g. single-sandbox-per-user flow): already "unlocked", return success
            return Response(status=status.HTTP_204_NO_CONTENT)
        SandboxLock.objects.filter(sandbox=sandbox.id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(
    methods=["GET"],
    responses={
        200: OpenApiResponse(response=serializers.TopologySerializer, description="Topology details"),
        **SANDBOX_RESPONSES
    }
)
class SandboxTopologyView(generics.RetrieveAPIView):
    """
    get: Get topology data for given sandbox.
    Hosts specified as hidden are filtered out, but the network is still visible.
    """
    queryset = Sandbox.objects.filter(ready=True)
    lookup_url_kwarg = "sandbox_uuid"
    serializer_class = serializers.TopologySerializer
    permission_classes = [IsAuthenticated, RetrieveSandboxForSelfOrOrganizerAdminPermission]

    def get_object(self):
        return sandboxes.get_sandbox_topology(super().get_object())



@extend_schema(
    methods=["GET"],
    responses={
        200: OpenApiResponse(response=serializers.NodeSerializer, description="Node details"),
        **SANDBOX_RESPONSES
    }
)
@extend_schema(
    methods=["PATCH"],
    request=serializers.NodeActionSerializer,
    responses={
        status.HTTP_200_OK: OpenApiResponse(description="Success, no content returned"),
        **SANDBOX_RESPONSES
    }
)
class SandboxVMDetailView(generics.GenericAPIView):
    queryset = Sandbox.objects.filter(ready=True)
    lookup_url_kwarg = "sandbox_uuid"
    serializer_class = serializers.NodeSerializer

    def get(self, request, *args, **kwargs):
        """Retrieve a VM info.
        Important Statuses:
        - ACTIVE (vm is active and running)
        - REBOOT (vm rebooting)
        - SUSPENDED (vm suspended)
        - ... https://developer.openstack.org/api-guide/compute/server_concepts.html#server-status
        """
        sandbox = self.get_object()
        node = nodes.get_node(sandbox, kwargs.get('vm_name'))
        return Response(serializers.NodeSerializer(node).data)

    def patch(self, request, *args, **kwargs):
        """Perform specified action on given VM.
        Available actions are:
        - suspend
        - resume
        - reboot
        """
        sandbox = self.get_object()
        try:
            action = request.data['action']
        except KeyError:
            raise exceptions.ValidationError("No action specified!")
        nodes.node_action(sandbox, kwargs.get('vm_name'), action)
        return Response()


class SandboxVMConsoleView(APIView):
    queryset = Sandbox.objects.none()

    @extend_schema(
        responses={
            200: OpenApiResponse(description="Console URL"),
            **SANDBOX_RESPONSES
        }
    )
    # noinspection PyMethodMayBeStatic
    def get(self, request, *args, **kwargs):
        """Get a console for given machine. It is active for 2 hours.
        But when the connection is active, it does not disconnect.
        """
        sandbox = sandboxes.get_sandbox(kwargs.get('sandbox_uuid'))
        console_url = nodes.get_console_url(sandbox, kwargs.get('vm_name'))
        return Response({'url': console_url}) if console_url else \
            Response(status=status.HTTP_202_ACCEPTED)


@extend_schema(
    responses={
        200: OpenApiResponse(description="SSH Config File"),
        **SANDBOX_RESPONSES
    }
)
class SandboxUserSSHAccessView(APIView):
    queryset = Sandbox.objects.none()

    # noinspection PyMethodMayBeStatic
    def get(self, request, *args, **kwargs):
        """Generate SSH config for User access to this sandbox.
        Some values are user specific, the config contains placeholders for them."""
        sandbox = sandboxes.get_sandbox(kwargs.get('sandbox_uuid'))
        in_memory_zip_file = sandboxes.get_user_ssh_access(sandbox)
        response = HttpResponse(FileWrapper(in_memory_zip_file),
                                content_type='application/zip')
        response['Content-Disposition'] = "attachment; filename=ssh-access.zip"
        return response


@extend_schema(
    responses={
        200: OpenApiResponse(description="Man IP"),
        **SANDBOX_RESPONSES
    }
)
class SandboxManOutPortIPView(APIView):
    queryset = Sandbox.objects.none()

    # noinspection PyMethodMayBeStatic
    def get(self, request, *args, **kwargs):
        """Retrieve a man out port ip address."""
        sandbox = sandboxes.get_sandbox(kwargs.get('sandbox_uuid'))
        man_ip = sandboxes.get_topology_instance(sandbox).ip
        return Response({"ip": man_ip})


@extend_schema(
    responses={
        200: OpenApiResponse(description="SSH Config File"),
        **SANDBOX_RESPONSES
    }
)
class PoolManagementSSHAccessView(APIView):
    queryset = Pool.objects.none()

    # noinspection PyMethodMayBeStatic
    def get(self, request, *args, **kwargs):
        """Generate SSH config for User access to this sandbox.
        Some values are user specific, the config contains placeholders for them."""
        pool = pools.get_pool(kwargs.get('pool_id'))
        in_memory_zip_file = pools.get_management_ssh_access(pool)
        response = HttpResponse(FileWrapper(in_memory_zip_file),
                                content_type='application/zip')
        response['Content-Disposition'] = "attachment; filename=ssh-access.zip"
        return response


class SandboxConsolesView(APIView):
    queryset = Sandbox.objects.none()

    @extend_schema(
        responses={
            200: OpenApiResponse(description='Console URLs'),
            **SANDBOX_RESPONSES
        },
        description='Console URLs'
    )
    # noinspection PyMethodMayBeStatic
    def get(self, request, *args, **kwargs):
        """Retrieve spice console urls for all machines in the topology. Returns 202 if
        consoles are not ready yet."""
        sandbox = sandboxes.get_sandbox(kwargs.get('sandbox_uuid'))
        topology_instance = sandboxes.get_topology_instance(sandbox)
        node_names = [host.name for host in topology_instance.get_hosts() if not host.hidden] + \
                     [router.name for router in topology_instance.get_routers()]
        consoles = {}
        is_ready = True
        for name in node_names:
            console_url = nodes.get_console_url(sandbox, name)
            if not console_url:
                is_ready = False
            consoles[name] = console_url
        return Response(consoles) if is_ready else Response(status=status.HTTP_202_ACCEPTED)


@extend_schema(
    responses={200: OpenApiResponse(description='Variables List'), **SANDBOX_RESPONSES}
)
class PoolVariablesView(APIView):
    queryset = Pool.objects.none()

    # noinspection PyMethodMayBeStatic
    def get(self, request, *args, **kwargs):
        """Retrieve APG variables from sandbox definition of this pool, empty list if variables.yml
        was not found."""
        pool = utils.get_object_or_404(Pool, pk=kwargs.get('pool_id'))
        definition = pool.definition
        variable_names = []
        try:
            variables = definitions.get_variables(definition.url, definition.rev,
                                                  settings.CRCZP_CONFIG)
            variable_names = [variable.name for variable in variables]
        except exceptions.GitError:
            pass
        return Response({"variables": variable_names})


@extend_schema(
    responses={200: OpenApiResponse(
        response=serializers.NodeAccessDataSerializer,
        description='Information necessary to access the node via Guacamole or other alternative.'), **SANDBOX_RESPONSES}
)
class TopologyNodeConnectionData(APIView):
    queryset = Sandbox.objects.none()
    serializer_class = serializers.NodeAccessDataSerializer

    # noinspection PyMethodMayBeStatic
    def get(self, request, *args, **kwargs):
        """Retrieves data needed to establish connection to a node in the topology."""
        sandbox = sandboxes.get_sandbox(kwargs.get('sandbox_uuid'))
        if sandbox is None:
            raise Http404(f"Sandbox with UUID {kwargs.get('sandbox_uuid')} does not exist.")
        node_name = kwargs.get('node_name')
        topology_instance = sandboxes.get_topology_instance(sandbox)
        node = topology_instance.get_node(node_name)
        if node is None:
            raise Http404(f"Node with name {node_name} does not exist in the topology of sandbox {sandbox.id}.")
        return Response(serializers.NodeAccessDataSerializer(nodes.get_node_access_data(topology_instance, node)).data)
