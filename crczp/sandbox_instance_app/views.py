from wsgiref.util import FileWrapper

import structlog
from django.conf import settings
from django.http import HttpResponse, Http404
from django.contrib.auth.models import AnonymousUser
from django.utils.decorators import method_decorator
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiRequest, OpenApiParameter
from rest_framework import status, generics
from rest_framework.response import Response
from rest_framework.views import APIView

from crczp.sandbox_common_lib import exceptions, utils
from crczp.sandbox_common_lib.utils import get_object_or_404
from crczp.sandbox_definition_app.lib import definitions
from crczp.sandbox_definition_app.serializers import DefinitionSerializer

from crczp.sandbox_instance_app import serializers
from crczp.sandbox_instance_app.lib import pools, sandboxes, nodes,\
    requests as sandbox_requests
from crczp.sandbox_instance_app.models import Pool, Sandbox, SandboxAllocationUnit, \
    AllocationRequest, CleanupRequest, SandboxLock, PoolLock
from crczp.sandbox_instance_app.lib import stage_handlers
from crczp.sandbox_common_lib.swagger_typing import PoolResponseSerializer, SandboxDefinitionSerializer, \
    PoolRequestSerializer, PoolRequestSerializer, PoolResponseSerializer
from crczp.sandbox_uag.permissions import AdminPermission, OrganizerPermission

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
    get: Get a list of Sandbox Allocation Units.
    """
    serializer_class = serializers.SandboxAllocationUnitSerializer

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
        """
        pool = pools.get_pool(kwargs.get('pool_id'))
        count = request.GET.get('count')
        if count is not None:
            try:
                count = int(count)
            except ValueError:
                raise exceptions.ValidationError("Invalid parameter count: %s" % count)

        created_by = None if isinstance(request.user, AnonymousUser) else request.user
        units = pools.create_sandboxes_in_pool(pool, created_by, count=count)
        serializer = self.serializer_class(units, many=True)
        page = self.paginate_queryset(serializer.data)
        if page is not None:
            return self.get_paginated_response(page)

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
    """get: Retrieve a Sandbox Allocation Unit."""
    serializer_class = serializers.SandboxAllocationUnitSerializer
    queryset = SandboxAllocationUnit.objects.all()
    lookup_url_kwarg = "unit_id"

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
class TerraformAllocationStageOutputListView(generics.ListAPIView):
    serializer_class = serializers.AllocationTerraformOutputSerializer

    def get_queryset(self):
        request_id = self.kwargs.get('request_id')
        request = get_object_or_404(AllocationRequest, pk=request_id)
        return request.stackallocationstage.terraform_outputs.all()


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
    permissions_classes = [OrganizerPermission | AdminPermission]


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
        """Delete lock of given sandbox allocation unit if it has sandbox."""
        allocation_unit = self.get_object()
        if not hasattr(allocation_unit, "sandbox"):
            raise Http404(f'Sandbox allocation unit {allocation_unit.id} has no sandbox.')
        sandbox = allocation_unit.sandbox
        if not hasattr(sandbox, "lock"):
            raise Http404(f'No SandboxLock matches the given query')
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
