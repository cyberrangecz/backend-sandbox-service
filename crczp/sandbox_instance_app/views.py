"""REST API views for sandbox instance management."""

import shlex
from typing import Any, override
from wsgiref.util import FileWrapper

import structlog
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.db.models import QuerySet
from django.http import Http404, HttpResponse
from drf_spectacular.utils import OpenApiParameter, OpenApiRequest, OpenApiResponse, extend_schema
from rest_framework import generics, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from crczp.sandbox_common_lib import exceptions, log_output_mixin, utils
from crczp.sandbox_common_lib.netbird_client import get_client_management_url
from crczp.sandbox_common_lib.swagger_typing import (
    PoolRequestSerializer,
    PoolResponseSerializer,
    SandboxDefinitionSerializer,
)
from crczp.sandbox_common_lib.utils import get_object_or_404
from crczp.sandbox_definition_app.lib import definitions
from crczp.sandbox_definition_app.serializers import DefinitionSerializer
from crczp.sandbox_instance_app import serializers
from crczp.sandbox_instance_app.lib import nodes, pools, sandboxes, stage_handlers
from crczp.sandbox_instance_app.lib import requests as sandbox_requests
from crczp.sandbox_instance_app.models import (
    AllocationRequest,
    CleanupRequest,
    Pool,
    PoolLock,
    Sandbox,
    SandboxAllocationUnit,
    SandboxLock,
    SandboxNetbirdAccess,
)
from crczp.sandbox_uag.permissions import AdminPermission, OrganizerPermission

LOG = structlog.get_logger()

COMMON_RESPONSE_PATTERNS = {
    401: OpenApiResponse(description='Unauthorized'),
    403: OpenApiResponse(description='Forbidden'),
    404: OpenApiResponse(description='Not Found'),
    500: OpenApiResponse(description='Internal Server Error'),
}

POOL_RESPONSES = {**COMMON_RESPONSE_PATTERNS, 400: OpenApiResponse(description='Bad Request')}
SANDBOX_RESPONSES = {**COMMON_RESPONSE_PATTERNS}


@extend_schema(
    methods=['GET'],
    responses={
        200: OpenApiResponse(
            response=serializers.PoolSerializer(many=True), description='List of Pools'
        ),
        **{k: v for k, v in utils.ERROR_RESPONSES.items() if k in [401, 403, 500]},
    },
)
class PoolListCreateView(generics.ListCreateAPIView[Any]):
    """
    get: Get a list of pools.
    """

    queryset = Pool.objects.all()
    serializer_class = serializers.PoolSerializer

    @extend_schema(
        request=OpenApiRequest(PoolRequestSerializer),
        responses={
            201: OpenApiResponse(response=PoolResponseSerializer, description='Pool created'),
            **POOL_RESPONSES,
        },
    )
    @override
    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Creates new pool.
        Also creates a new key-pair and certificate, which is then passed to terraform client.
        The key is then used as management key for this pool, which means that the management
         key-pair is the same for each sandbox in the pool.
        """
        created_by = None if isinstance(request.user, AnonymousUser) else request.user
        pool = pools.create_pool(request.data, created_by)
        serializer = self.serializer_class(pool)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


@extend_schema(methods=['GET'], responses={200: PoolResponseSerializer, **POOL_RESPONSES})
class PoolDetailDeleteUpdateView(generics.RetrieveDestroyAPIView[Any]):
    """
    get: Retrieve a pool.
    """

    queryset = Pool.objects.all()
    serializer_class = serializers.PoolSerializer
    lookup_url_kwarg = 'pool_id'

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name='force',
                type=bool,
                location=OpenApiParameter.QUERY,
                description='Force the deletion of sandboxes',
                required=False,
                default=False,
            ),
        ],
        responses={**POOL_RESPONSES},
    )
    @override
    def delete(self, request: Request, *args: Any, **kwargs: Any) -> Response:
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
        responses={200: serializers.PoolSerializer, **POOL_RESPONSES},
    )
    def patch(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Partially update a pool."""
        pool = self.get_object()
        serializer = self.serializer_class(pool, data=request.data, partial=True)

        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(methods=['GET'], responses={200: SandboxDefinitionSerializer, **SANDBOX_RESPONSES})
class PoolDefinitionView(generics.RetrieveAPIView[Any]):
    """
    get: Retrieve the definition associated with a pool.
    """

    queryset = Pool.objects.all()
    lookup_url_kwarg = 'pool_id'
    serializer_class = DefinitionSerializer

    @override
    def get_object(self) -> Any:
        return super().get_object().definition


@extend_schema(
    methods=['GET'],
    responses={
        200: OpenApiResponse(
            response=serializers.PoolLockSerializer(many=True), description='List of Pool Locks'
        ),
        **SANDBOX_RESPONSES,
    },
)
@extend_schema(
    methods=['POST'],
    request=OpenApiRequest(PoolRequestSerializer),
    responses={
        201: OpenApiResponse(response=PoolResponseSerializer, description='Pool created'),
        **POOL_RESPONSES,
    },
)
class PoolLockListCreateView(generics.ListCreateAPIView[Any]):
    """
    get: List locks for given pool.
    """

    serializer_class = serializers.PoolLockSerializer

    @override
    def get_queryset(self) -> QuerySet[Any, Any]:
        pool_id = self.kwargs.get('pool_id')
        get_object_or_404(Pool, pk=pool_id)
        return PoolLock.objects.filter(pool=pool_id)

    @override
    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Lock given pool."""
        pool = pools.get_pool(kwargs['pool_id'])
        training_access_token = request.data.get('training_access_token', None)
        lock = pools.lock_pool(pool, training_access_token)
        return Response(self.serializer_class(lock).data, status=status.HTTP_201_CREATED)


@extend_schema(
    methods=['GET'],
    responses={200: OpenApiResponse(response=serializers.PoolLockSerializer), **SANDBOX_RESPONSES},
)
@extend_schema(
    methods=['DELETE'],
    responses={204: OpenApiResponse(description='No Content'), **SANDBOX_RESPONSES},
)
class PoolLockDetailDeleteView(generics.RetrieveDestroyAPIView[Any]):
    """
    get: Retrieve details about given lock.
    delete: Delete given lock.
    """

    queryset = PoolLock.objects.all()
    lookup_url_kwarg = 'lock_id'
    serializer_class = serializers.PoolLockSerializer


@extend_schema(
    methods=['GET'],
    responses={
        200: OpenApiResponse(
            response=serializers.AllocationRequestSerializer(many=True),
            description='List of Allocation Requests',
        ),
        **SANDBOX_RESPONSES,
    },
)
class PoolAllocationRequestListView(generics.ListAPIView[Any]):
    """
    get: List Allocation Request for this pool.
    """

    serializer_class = serializers.AllocationRequestSerializer

    @override
    def get_queryset(self) -> QuerySet[Any, Any]:
        pool_id = self.kwargs.get('pool_id')
        pool = get_object_or_404(Pool, pk=pool_id)
        return AllocationRequest.objects.filter(allocation_unit__in=pool.allocation_units.all())


@extend_schema(
    methods=['GET'],
    responses={
        200: OpenApiResponse(
            response=serializers.CleanupRequestSerializer(many=True),
            description='List of Cleanup Requests',
        ),
        **SANDBOX_RESPONSES,
    },
)
@extend_schema(
    methods=['POST'],
    parameters=[
        OpenApiParameter(
            name='force',
            type=bool,
            location=OpenApiParameter.QUERY,
            description='Force the deletion of sandboxes',
            required=False,
        )
    ],
    responses={
        201: OpenApiResponse(
            response=serializers.CleanupRequestSerializer, description='Cleanup Request created'
        ),
        **POOL_RESPONSES,
    },
)
class PoolCleanupRequestsListCreateView(generics.ListCreateAPIView[Any]):
    """
    get: List Cleanup Requests for this pool.
    """

    serializer_class = serializers.CleanupRequestSerializer

    @override
    def get_queryset(self) -> QuerySet[Any, Any]:
        pool_id = self.kwargs.get('pool_id')
        get_object_or_404(Pool, pk=pool_id)
        return CleanupRequest.objects.filter(allocation_unit__pool_id=pool_id)

    @override
    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Deletes all sandboxes in the pool. With an optional parameter *force*,
        it forces the deletion."""
        pool_id = kwargs['pool_id']
        get_object_or_404(Pool, pk=pool_id)
        pool_units = SandboxAllocationUnit.objects.filter(pool_id=pool_id)
        force = request.GET.get('force', 'false') == 'true'
        sandbox_requests.create_cleanup_requests(pool_units, force)
        return Response(status=status.HTTP_201_CREATED)


class PoolCleanupRequestUnlockedCreateView(APIView):
    """API view to create cleanup requests for unlocked sandboxes in a pool."""

    serializer_class = serializers.PoolCleanupRequestSerializer
    queryset = CleanupRequest.objects.none()

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name='force',
                type=bool,
                location=OpenApiParameter.QUERY,
                description='Force the deletion of sandboxes',
                required=False,
            )
        ]
    )
    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Deletes all unlocked sandboxes in a pool. With an optional parameter *force*, it forces
        the deletion."""
        pool_id = kwargs['pool_id']
        get_object_or_404(Pool, pk=pool_id)
        all_pool_units = SandboxAllocationUnit.objects.filter(pool_id=pool_id)
        pool_units = [
            unit
            for unit in all_pool_units
            if hasattr(unit, 'sandbox') and not hasattr(unit.sandbox, 'lock')
        ]
        force = request.GET.get('force', 'false') == 'true'
        sandbox_requests.create_cleanup_requests(pool_units, force)
        return Response(status=status.HTTP_201_CREATED)


class PoolCleanupRequestFailedCreateView(APIView):
    """API view to create cleanup requests for failed sandboxes in a pool."""

    serializer_class = serializers.PoolCleanupRequestFailedSerializer
    queryset = CleanupRequest.objects.none()

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name='force',
                type=bool,
                location=OpenApiParameter.QUERY,
                description='Force the deletion of sandboxes',
                required=False,
            )
        ],
        responses={201: OpenApiResponse(description='Cleanup Request created')},
    )
    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Deletes all failed sandboxes in a pool. With an optional parameter *force*, it forces
        the deletion."""
        pool_id = kwargs['pool_id']
        get_object_or_404(Pool, pk=pool_id)
        all_pool_units = SandboxAllocationUnit.objects.filter(pool_id=pool_id)
        force = request.GET.get('force', 'false') == 'true'
        pool_units = [
            unit
            for unit in all_pool_units
            if unit.allocation_request.stages.filter(failed=True).count()
        ]
        sandbox_requests.create_cleanup_requests(pool_units, force)
        return Response(status=status.HTTP_201_CREATED)


@extend_schema(
    responses={
        200: OpenApiResponse(
            response=serializers.SandboxAllocationUnitSerializer(many=True),
            description='List of Sandbox Allocation Units',
        ),
        **SANDBOX_RESPONSES,
    }
)
class SandboxAllocationUnitListCreateView(generics.ListCreateAPIView[Any]):
    """
    get: Get a list of Sandbox Allocation Units.
    """

    serializer_class = serializers.SandboxAllocationUnitSerializer

    @override
    def get_queryset(self) -> QuerySet[Any, Any]:
        return SandboxAllocationUnit.objects.filter(pool_id=self.kwargs['pool_id'])

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name='count',
                type=int,
                location=OpenApiParameter.QUERY,
                description='Sandbox count parameter',
                required=False,
            )
        ],
        responses={
            status.HTTP_201_CREATED: OpenApiResponse(
                response=serializers.SandboxAllocationUnitSerializer(many=True),
                description='Created Sandbox Allocation Units',
            ),
            **POOL_RESPONSES,
        },
    )
    @override
    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Create Sandbox Allocation Unit.
        For each Allocation Unit the Allocation Request is created in given pool.
        If count is not specified, builds *max_size - current size*.
        Query Parameters:
        - *count:* How many sandboxes to build. Optional (defaults to max_size - current size).
        """
        pool = pools.get_pool(kwargs['pool_id'])
        count_param = request.GET.get('count')
        count: int | None = None
        if count_param is not None:
            try:
                count = int(count_param)
            except ValueError:
                raise exceptions.ValidationError(
                    f'Invalid parameter count: {count_param}'
                ) from None

        created_by = None if isinstance(request.user, AnonymousUser) else request.user
        units = pools.create_sandboxes_in_pool(pool, created_by, count=count)
        serializer = self.serializer_class(units, many=True)
        page = self.paginate_queryset(serializer.data)  # type: ignore[arg-type]
        if page is not None:
            return self.get_paginated_response(page)

        return Response(serializer.data, status=status.HTTP_201_CREATED)


@extend_schema(
    methods=['GET'],
    responses={
        200: OpenApiResponse(
            response=serializers.SandboxAllocationUnitSerializer(),
            description='Retrieve a Sandbox Allocation Unit',
        ),
        **SANDBOX_RESPONSES,
    },
)
@extend_schema(
    methods=['PATCH'],
    request=serializers.SandboxAllocationUnitSerializer,
    responses={
        200: OpenApiResponse(
            response=serializers.SandboxAllocationUnitSerializer(),
            description='Updated Sandbox Allocation Unit',
        ),
        **POOL_RESPONSES,
    },
)
class SandboxAllocationUnitDetailUpdateView(generics.RetrieveAPIView[Any]):
    """get: Retrieve a Sandbox Allocation Unit."""

    serializer_class = serializers.SandboxAllocationUnitSerializer
    queryset = SandboxAllocationUnit.objects.all()
    lookup_url_kwarg = 'unit_id'

    def patch(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Partially update a sandbox allocation unit."""
        allocation_unit = self.get_object()
        serializer = self.serializer_class(allocation_unit, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(
    methods=['GET'],
    responses={
        200: OpenApiResponse(
            response=serializers.AllocationRequestSerializer(),
            description='Retrieve Allocation Request',
        ),
        **SANDBOX_RESPONSES,
    },
)
class SandboxAllocationRequestView(generics.RetrieveAPIView[Any]):
    """
    get: Retrieve a Sandbox Allocation Request for an Allocation Unit.
    Each Allocation Unit has exactly one Allocation Request.
    (There may occur a situation where it has none, then it returns 404.)
    """

    queryset = SandboxAllocationUnit.objects.all()
    lookup_url_kwarg = 'unit_id'
    serializer_class = serializers.AllocationRequestSerializer

    @override
    def get_object(self) -> Any:
        unit = super().get_object()
        try:
            return unit.allocation_request
        except AttributeError:
            raise Http404(
                f'The allocation unit (ID={unit.id}) has no allocation request.'
            ) from None


@extend_schema(
    methods=['GET'],
    responses={
        200: OpenApiResponse(
            response=serializers.AllocationRequestSerializer(),
            description='Retrieve Allocation Request',
        ),
        **SANDBOX_RESPONSES,
    },
)
class AllocationRequestDetailView(generics.RetrieveAPIView[Any]):
    """get: Retrieve a Sandbox Allocation Request."""

    queryset = AllocationRequest.objects.all()
    serializer_class = serializers.AllocationRequestSerializer
    lookup_url_kwarg = 'request_id'


class AllocationRequestCancelView(generics.GenericAPIView[Any]):
    """API view to cancel an allocation request."""

    serializer_class = serializers.AllocationRequestSerializer
    queryset = AllocationRequest.objects.all()
    lookup_url_kwarg = 'request_id'

    @extend_schema(
        responses={
            status.HTTP_200_OK: OpenApiResponse(description='Success, no content'),
            **POOL_RESPONSES,
        }
    )
    def patch(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Cancel given Allocation Request. Returns no data if OK (200)."""
        sandbox_requests.cancel_allocation_request(self.get_object())
        return Response()


@extend_schema(
    methods=['GET'],
    responses={
        200: OpenApiResponse(
            response=serializers.CleanupRequestSerializer(), description='Retrieve Cleanup Request'
        ),
        **SANDBOX_RESPONSES,
    },
)
class SandboxCleanupRequestView(generics.RetrieveDestroyAPIView[Any], generics.CreateAPIView[Any]):  # pylint: disable=too-many-ancestors
    """API view to get, create, or delete a sandbox cleanup request."""

    queryset = SandboxAllocationUnit.objects.all()
    lookup_url_kwarg = 'unit_id'
    serializer_class = serializers.CleanupRequestSerializer

    @override
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Retrieve a Sandbox Cleanup Request for an Allocation Unit.
        Each Allocation Unit has at most one Cleanup Request.
        If it has none, then it returns 404.
        """
        unit = self.get_object()
        try:
            request = unit.cleanup_request
        except AttributeError:
            raise Http404(f'The allocation unit (ID={unit.id}) has no cleanup request.') from None
        serializer = self.get_serializer(request)
        return Response(serializer.data)

    @extend_schema(
        responses={
            201: serializers.CleanupRequestSerializer,
        }
    )
    @override
    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Create cleanup request."""
        unit = self.get_object()
        force = request.GET.get('force', 'false') == 'true'
        sandbox_requests.create_cleanup_requests([unit], force)
        return Response(status=status.HTTP_201_CREATED)

    @override
    def delete(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Delete cleanup request. Must be finished or cancelled."""
        unit = self.get_object()
        sandbox_requests.delete_cleanup_request(unit.cleanup_request)
        return Response({}, status=status.HTTP_204_NO_CONTENT)


class SandboxAllocationStagesRestartView(generics.GenericAPIView[Any]):
    """API view to restart failed sandbox allocation stages."""

    serializer_class = serializers.SandboxAllocationUnitSerializer
    queryset = SandboxAllocationUnit.objects.all()
    lookup_url_kwarg = 'unit_id'

    @extend_schema(
        responses={
            status.HTTP_201_CREATED: serializers.SandboxAllocationUnitSerializer,
            **POOL_RESPONSES,
        }
    )
    def patch(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Restart all failed sandbox allocation stages.
        """
        allocation_unit = self.get_object()
        allocation_unit_updated = sandbox_requests.restart_allocation_stages(allocation_unit)

        serializer = self.serializer_class(allocation_unit_updated)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


@extend_schema(
    methods=['GET'],
    responses={
        200: OpenApiResponse(
            response=serializers.CleanupRequestSerializer, description='Retrieve Cleanup Request'
        ),
        **SANDBOX_RESPONSES,
    },
)
class CleanupRequestDetailView(generics.RetrieveAPIView[Any]):
    """get: Retrieve a Sandbox Cleanup Request."""

    serializer_class = serializers.CleanupRequestSerializer
    queryset = CleanupRequest.objects.all()
    lookup_url_kwarg = 'request_id'


class CleanupRequestCancelView(generics.GenericAPIView[Any]):
    """API view to cancel a cleanup request."""

    serializer_class = serializers.CleanupRequestSerializer
    queryset = CleanupRequest.objects.all()
    lookup_url_kwarg = 'request_id'

    @extend_schema(
        responses={
            status.HTTP_200_OK: OpenApiResponse(description='Success, no content'),
            **POOL_RESPONSES,
        }
    )
    def patch(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Cancel given Cleanup Request. Returns no data if OK (200)."""
        sandbox_requests.cancel_cleanup_request(self.get_object())
        return Response()


@extend_schema(
    methods=['GET'],
    responses={
        200: OpenApiResponse(
            response=serializers.AllocationTerraformOutputSerializer(many=True),
            description='List of Terraform Outputs',
        ),
        **SANDBOX_RESPONSES,
    },
)
class TerraformAllocationStageDetailView(generics.RetrieveAPIView[Any]):
    """
    get: Retrieve an `openstack` allocation stage.
    Null `status` and `status_reason` attributes mean, that stack does not have them;
    AKA it does not exist in OpenStack.
    """

    serializer_class = serializers.TerraformAllocationStageSerializer
    queryset = AllocationRequest.objects.all()
    lookup_url_kwarg = 'request_id'

    @override
    def get_object(self) -> Any:
        request = super().get_object()
        return stage_handlers.AllocationStackStageHandler(request.stackallocationstage).stage


@extend_schema(
    methods=['GET'],
    responses={
        200: OpenApiResponse(
            response=serializers.TerraformCleanupStageSerializer,
            description='Retrieve Terraform Cleanup Stage',
        ),
        **SANDBOX_RESPONSES,
    },
)
class TerraformCleanupStageDetailView(generics.RetrieveAPIView[Any]):
    """get: Retrieve an `openstack` Cleanup stage."""

    serializer_class = serializers.TerraformCleanupStageSerializer
    queryset = CleanupRequest.objects.all()
    lookup_url_kwarg = 'request_id'

    @override
    def get_object(self) -> Any:
        request = super().get_object()
        return request.stackcleanupstage


@extend_schema(
    methods=['GET'],
    responses={
        200: OpenApiResponse(
            response=serializers.AllocationTerraformOutputSerializer(many=True),
            description='List of Terraform Outputs',
        ),
        **SANDBOX_RESPONSES,
    },
)
class TerraformAllocationStageOutputListView(log_output_mixin.CompressedOutputMixin, APIView):
    """API view to list terraform allocation stage log output."""

    queryset = AllocationRequest.objects.all()

    def get(self, request: Request, request_id: int) -> Response:
        """List terraform allocation stage log output."""
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
    methods=['GET'],
    responses={
        200: OpenApiResponse(
            response=serializers.SandboxSerializer(many=True), description='List of Sandboxes'
        ),
        **SANDBOX_RESPONSES,
    },
)
class PoolSandboxListView(generics.ListAPIView[Any]):
    """API view to list all ready sandboxes in a pool."""

    serializer_class = serializers.SandboxSerializer
    permission_classes = [OrganizerPermission | AdminPermission]

    @override
    def get_queryset(self) -> QuerySet[Any, Any]:
        pool_id = self.kwargs.get('pool_id')
        pool = get_object_or_404(Pool, pk=pool_id)
        alloc_unit_ids = [unit.id for unit in pool.allocation_units.all()]
        return Sandbox.objects.filter(allocation_unit_id__in=alloc_unit_ids, ready=True)


class SandboxGetAndLockView(generics.RetrieveAPIView[Any]):
    """API view to retrieve an unlocked sandbox from a pool and lock it."""

    serializer_class = serializers.SandboxSerializer
    queryset = Sandbox.objects.filter(ready=True)  # To allow trainee to access training run!
    lookup_url_kwarg = 'pool_id'

    @extend_schema(
        responses={
            status.HTTP_409_CONFLICT: OpenApiResponse(
                description='No free sandboxes; all sandboxes are locked.',
                response=utils.ErrorSerilizer,
            ),
            **SANDBOX_RESPONSES,
        }
    )
    @override
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Get unlocked sandbox in given pool and lock it.
        Return 409 if all are locked, 403 if training access token invalid
        or 400 if there is no lock.
        """
        pool_id = self.kwargs.get('pool_id')
        pool = get_object_or_404(Pool, id=pool_id)
        training_access_token = self.kwargs.get('training_access_token')

        if hasattr(pool, 'lock'):
            if pool.lock.training_access_token is None:
                return Response(
                    {'detail': 'This pool does not have a training assigned'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            if pool.lock.training_access_token != training_access_token:
                return Response(
                    {'detail': 'Provided training access token is not valid.'},
                    status=status.HTTP_403_FORBIDDEN,
                )
        else:
            return Response(
                {'detail': 'The pool is not locked.'}, status=status.HTTP_400_BAD_REQUEST
            )

        created_by = None if isinstance(request.user, AnonymousUser) else request.user
        sandbox = pools.get_unlocked_sandbox(pool, created_by)
        if not sandbox:
            return Response(
                {'detail': 'All sandboxes are already locked.'}, status=status.HTTP_409_CONFLICT
            )
        return Response(self.serializer_class(sandbox).data)


#######################################
# SANDBOX MANIPULATION VIEWS #
#######################################


@extend_schema(
    methods=['GET'],
    responses={
        200: OpenApiResponse(response=serializers.SandboxSerializer, description='Sandbox details'),
        **SANDBOX_RESPONSES,
    },
)
class SandboxDetailView(generics.RetrieveAPIView[Any]):
    """get: Retrieve a sandbox."""

    serializer_class = serializers.SandboxSerializer
    lookup_url_kwarg = 'sandbox_uuid'
    queryset = Sandbox.objects.filter(ready=True)
    permissions_classes = [OrganizerPermission | AdminPermission]


@extend_schema(
    methods=['GET'],
    responses={
        200: OpenApiResponse(
            response=serializers.SandboxLockSerializer, description='Sandbox Lock details'
        ),
        **SANDBOX_RESPONSES,
    },
)
@extend_schema(
    methods=['POST'],
    responses={
        201: OpenApiResponse(
            response=serializers.SandboxLockSerializer, description='Sandbox Lock created'
        ),
        **SANDBOX_RESPONSES,
    },
)
class SandboxAllocationUnitLockRetrieveCreateDestroyView(
    generics.RetrieveDestroyAPIView[Any],
    generics.CreateAPIView[Any],  # pylint: disable=too-many-ancestors
):
    """
    post: Create locks for given sandbox allocation unit if its sandbox exists.
    delete: Destroy locks for given sandbox allocation unit if its sandbox exists."""

    queryset = SandboxAllocationUnit.objects.all()
    lookup_url_kwarg = 'unit_id'
    serializer_class = serializers.SandboxLockSerializer

    @override
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """get: Retrieve lock for given sandbox allocation unit if its sandbox exists."""
        allocation_unit = self.get_object()
        if not hasattr(allocation_unit, 'sandbox'):
            raise Http404(f'Sandbox allocation unit {allocation_unit.id} has no sandbox.')
        sandbox_id = allocation_unit.sandbox.id
        lock = SandboxLock.objects.get(sandbox=sandbox_id)
        return Response(self.get_serializer(lock).data)

    @override
    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Lock sandbox of given sandbox allocation unit if the sandbox exists."""
        allocation_unit = self.get_object()
        if not hasattr(allocation_unit, 'sandbox'):
            raise Http404(f'Sandbox allocation unit {allocation_unit.id} has no sandbox.')
        sandbox = allocation_unit.sandbox
        created_by = None if isinstance(request.user, AnonymousUser) else request.user
        lock = sandboxes.lock_sandbox(sandbox=sandbox, created_by=created_by)
        return Response(self.get_serializer(lock).data, status=status.HTTP_201_CREATED)

    @override
    def delete(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Delete lock of given sandbox allocation unit if it has sandbox."""
        allocation_unit = self.get_object()
        if not hasattr(allocation_unit, 'sandbox'):
            raise Http404(f'Sandbox allocation unit {allocation_unit.id} has no sandbox.')
        sandbox = allocation_unit.sandbox
        if not hasattr(sandbox, 'lock'):
            raise Http404('No SandboxLock matches the given query')
        SandboxLock.objects.filter(sandbox=sandbox.id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(
    methods=['GET'],
    responses={
        200: OpenApiResponse(
            response=serializers.TopologySerializer, description='Topology details'
        ),
        **SANDBOX_RESPONSES,
    },
)
class SandboxTopologyView(generics.RetrieveAPIView[Any]):
    """
    get: Get topology data for given sandbox.
    Hosts specified as hidden are filtered out, but the network is still visible.
    """

    queryset = Sandbox.objects.filter(ready=True)
    lookup_url_kwarg = 'sandbox_uuid'
    serializer_class = serializers.TopologySerializer

    @override
    def get_object(self) -> Any:
        return sandboxes.get_sandbox_topology(super().get_object())


@extend_schema(
    methods=['GET'],
    responses={
        200: OpenApiResponse(response=serializers.NodeSerializer, description='Node details'),
        **SANDBOX_RESPONSES,
    },
)
@extend_schema(
    methods=['PATCH'],
    request=serializers.NodeActionSerializer,
    responses={
        status.HTTP_200_OK: OpenApiResponse(description='Success, no content returned'),
        **SANDBOX_RESPONSES,
    },
)
class SandboxVMDetailView(generics.GenericAPIView[Any]):
    """API view to retrieve VM details and perform actions on a VM in a sandbox."""

    queryset = Sandbox.objects.filter(ready=True)
    lookup_url_kwarg = 'sandbox_uuid'
    serializer_class = serializers.NodeSerializer

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Retrieve a VM info.
        Important Statuses:
        - ACTIVE (vm is active and running)
        - REBOOT (vm rebooting)
        - SUSPENDED (vm suspended)
        - ... https://developer.openstack.org/api-guide/compute/server_concepts.html#server-status
        """
        sandbox = self.get_object()
        node = nodes.get_node(sandbox, kwargs['vm_name'])
        return Response(serializers.NodeSerializer(node).data)

    def patch(self, request: Request, *args: Any, **kwargs: Any) -> Response:
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
            raise exceptions.ValidationError('No action specified!') from None
        nodes.node_action(sandbox, kwargs['vm_name'], action)
        return Response()


class SandboxVMConsoleView(APIView):
    """API view to get a console URL for a VM in a sandbox."""

    queryset = Sandbox.objects.none()

    @extend_schema(responses={200: OpenApiResponse(description='Console URL'), **SANDBOX_RESPONSES})
    # noinspection PyMethodMayBeStatic
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Get a console for given machine. It is active for 2 hours.
        But when the connection is active, it does not disconnect.
        """
        sandbox = sandboxes.get_sandbox(kwargs['sandbox_uuid'])
        console_url = nodes.get_console_url(sandbox, kwargs['vm_name'])
        return (
            Response({'url': console_url})
            if console_url
            else Response(status=status.HTTP_202_ACCEPTED)
        )


@extend_schema(responses={200: OpenApiResponse(description='SSH Config File'), **SANDBOX_RESPONSES})
class SandboxUserSSHAccessView(APIView):
    """API view to generate SSH config for user access to a sandbox."""

    queryset = Sandbox.objects.none()

    # noinspection PyMethodMayBeStatic
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response | HttpResponse:
        """Generate SSH config for User access to this sandbox.
        Some values are user specific, the config contains placeholders for them."""
        sandbox = sandboxes.get_sandbox(kwargs['sandbox_uuid'])
        in_memory_zip_file = sandboxes.get_user_ssh_access(sandbox)
        response = HttpResponse(FileWrapper(in_memory_zip_file), content_type='application/zip')
        response['Content-Disposition'] = 'attachment; filename=ssh-access.zip'
        return response


@extend_schema(responses={200: OpenApiResponse(description='Man IP'), **SANDBOX_RESPONSES})
class SandboxManOutPortIPView(APIView):
    """API view to retrieve the MAN out-port IP address for a sandbox."""

    queryset = Sandbox.objects.none()

    # noinspection PyMethodMayBeStatic
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Retrieve a man out port ip address."""
        sandbox = sandboxes.get_sandbox(kwargs['sandbox_uuid'])
        man_ip = sandboxes.get_topology_instance(sandbox).ip
        return Response({'ip': man_ip})


@extend_schema(responses={200: OpenApiResponse(description='SSH Config File'), **SANDBOX_RESPONSES})
class PoolManagementSSHAccessView(APIView):
    """API view to generate management SSH access config for a pool."""

    queryset = Pool.objects.none()

    # noinspection PyMethodMayBeStatic
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response | HttpResponse:
        """Generate SSH config for User access to this sandbox.
        Some values are user specific, the config contains placeholders for them."""
        pool = pools.get_pool(kwargs['pool_id'])
        in_memory_zip_file = pools.get_management_ssh_access(pool)
        response = HttpResponse(FileWrapper(in_memory_zip_file), content_type='application/zip')
        response['Content-Disposition'] = 'attachment; filename=ssh-access.zip'
        return response


class SandboxConsolesView(APIView):
    """API view to retrieve SPICE console URLs for all nodes in a sandbox topology."""

    queryset = Sandbox.objects.none()

    @extend_schema(
        responses={200: OpenApiResponse(description='Console URLs'), **SANDBOX_RESPONSES},
        description='Console URLs',
    )
    # noinspection PyMethodMayBeStatic
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Retrieve spice console urls for all machines in the topology. Returns 202 if
        consoles are not ready yet."""
        sandbox = sandboxes.get_sandbox(kwargs['sandbox_uuid'])
        topology_instance = sandboxes.get_topology_instance(sandbox)
        node_names = [host.name for host in topology_instance.get_hosts() if not host.hidden] + [
            router.name for router in topology_instance.get_routers()
        ]
        consoles = {}
        is_ready = True
        for name in node_names:
            console_url = nodes.get_console_url(sandbox, name)
            if not console_url:
                is_ready = False
            consoles[name] = console_url
        return Response(consoles) if is_ready else Response(status=status.HTTP_202_ACCEPTED)


@extend_schema(responses={200: OpenApiResponse(description='Variables List'), **SANDBOX_RESPONSES})
class PoolVariablesView(APIView):
    """API view to retrieve APG variable names from a pool's sandbox definition."""

    queryset = Pool.objects.none()

    # noinspection PyMethodMayBeStatic
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Retrieve APG variables from sandbox definition of this pool, empty list if variables.yml
        was not found."""
        pool = utils.get_object_or_404(Pool, pk=kwargs['pool_id'])
        definition = pool.definition
        variable_names = []
        try:
            variables = definitions.get_variables(
                definition.url, definition.rev, settings.CRCZP_CONFIG
            )
            variable_names = [variable.name for variable in variables]
        except exceptions.GitError:
            pass
        return Response({'variables': variable_names})


@extend_schema(
    responses={
        200: OpenApiResponse(
            response=serializers.NodeAccessDataSerializer,
            description=(
                'Information necessary to access the node via Guacamole or other alternative.'
            ),
        ),
        **SANDBOX_RESPONSES,
    }
)
class TopologyNodeConnectionData(APIView):
    """API view to retrieve connection data for a node in a sandbox topology."""

    queryset = Sandbox.objects.none()
    serializer_class = serializers.NodeAccessDataSerializer

    # noinspection PyMethodMayBeStatic
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Retrieves data needed to establish connection to a node in the topology."""
        sandbox = sandboxes.get_sandbox(kwargs['sandbox_uuid'])
        if sandbox is None:
            raise Http404(f'Sandbox with UUID {kwargs["sandbox_uuid"]} does not exist.')
        node_name = kwargs['node_name']
        topology_instance = sandboxes.get_topology_instance(sandbox)
        node = topology_instance.get_node(node_name)
        if node is None:
            raise Http404(
                f'Node with name {node_name} does not exist'
                f' in the topology of sandbox {sandbox.id}.'
            )
        return Response(
            serializers.NodeAccessDataSerializer(
                nodes.get_node_access_data(topology_instance, node)
            ).data
        )


@extend_schema(
    responses={
        200: OpenApiResponse(
            response=serializers.SandboxVpnConfigSerializer,
            description='Netbird VPN client configuration for this sandbox.',
        ),
        **SANDBOX_RESPONSES,
    }
)
class SandboxVpnView(APIView):
    """
    Returns the Netbird VPN client configuration for this sandbox.

    A single shared access setup key grants a client access to every VPN
    entrypoint of the sandbox; ``routes`` is the union of the CIDRs reachable
    through those entrypoints. ``setup_key`` is null while the access resources
    are still being provisioned (or when the sandbox has no VPN entrypoints).

    ``command`` is the ready-to-run NetBird CLI line a client pastes to connect
    (it embeds ``management_url`` and ``setup_key``); it is null whenever
    ``setup_key`` is null, so the frontend can key its connect button off either
    field. The structured ``management_url``/``setup_key``/``routes`` fields are
    retained so callers can also consume the configuration programmatically or
    render the reachable ``routes``.

    Uses the default permission classes (like the sibling sandbox read views),
    so it is accessible to any authenticated user who can read the sandbox,
    including trainees.
    """

    queryset = Sandbox.objects.none()
    serializer_class = serializers.SandboxVpnConfigSerializer

    # noinspection PyMethodMayBeStatic
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Returns the Netbird VPN client configuration for this sandbox."""
        sandbox = sandboxes.get_sandbox(self.kwargs['sandbox_uuid'])
        access = SandboxNetbirdAccess.objects.filter(sandbox=sandbox).first()
        setup_key = access.access_setup_key_value if access else None
        management_url = get_client_management_url()

        routes: list[str] = []
        command: str | None = None
        if setup_key:
            for nbr in sandbox.netbird_resources.all():
                routes.extend(nbr.get_route_cidr_list())
            routes = list(dict.fromkeys(routes))
            # Build the command server-side so the NetBird CLI syntax lives in
            # one place; shlex.quote keeps a key/URL with shell-special
            # characters from breaking when pasted into a shell.
            command = (
                f'netbird up --management-url {shlex.quote(management_url)}'
                f' --setup-key {shlex.quote(setup_key)}'
            )

        return Response({
            'management_url': management_url,
            'setup_key': setup_key,
            'routes': routes,
            'command': command,
        })
