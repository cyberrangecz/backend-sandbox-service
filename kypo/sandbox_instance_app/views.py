import io
from wsgiref.util import FileWrapper

import structlog
from django.conf import settings
from django.http import HttpResponse, Http404
from django.utils.module_loading import import_string
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status, generics, mixins
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from kypo.sandbox_definition_app.models import Definition
from kypo.sandbox_definition_app.serializers import DefinitionSerializer
from kypo.sandbox_instance_app.lib.stage_handlers import StackStageHandler
from kypo.sandbox_instance_app import serializers
from kypo.sandbox_instance_app.lib import units, pools, sandboxes, nodes,\
    sandbox_destructor
from kypo.sandbox_instance_app.models import Pool, Sandbox, SandboxAllocationUnit, \
    AllocationRequest, \
    AllocationStage, StackAllocationStage, CleanupRequest, StackCleanupStage, CleanupStage, \
    SandboxLock, PoolLock
from kypo.sandbox_common_lib import exceptions
from kypo.sandbox_common_lib.permissions import AllowReadOnViewSandbox

# Create logger and configure logging
LOG = structlog.get_logger()


class PoolList(mixins.ListModelMixin,
               generics.GenericAPIView):
    queryset = Pool.objects.all()
    serializer_class = serializers.PoolSerializer

    def get(self, request, *args, **kwargs):
        """Get a list of pools."""
        return self.list(request, *args, **kwargs)

    @staticmethod
    def post(request):
        """Creates new pool.
        Also creates a new key-pair in OpenStack for this pool.
        It is then used as management key for this pool. That means that
        the management key-pair is the same for each sandbox in the pool.
        Parameter `rev` is optional. Defaults to definition rev.
        If ref is a branch, uses current HEAD.
        """
        pool = pools.create_pool(request.data)
        serializer = serializers.PoolSerializer(pool)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class PoolDetail(mixins.RetrieveModelMixin,
                 mixins.DestroyModelMixin,
                 generics.GenericAPIView):
    queryset = Pool.objects.all()
    serializer_class = serializers.PoolSerializer
    lookup_url_kwarg = "pool_id"

    def get(self, request, *args, **kwargs):
        """Retrieve a pool."""
        return self.retrieve(request, *args, **kwargs)

    # noinspection PyUnusedLocal
    def delete(self, request, pool_id):
        """Delete pool. The pool must be empty.
        First delete all sandboxes in given Pool.
        """
        pool = self.get_object()
        pools.delete_pool(pool)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PoolDefinition(mixins.RetrieveModelMixin, generics.GenericAPIView):
    queryset = Definition.objects.none()  # Required for DjangoModelPermissions
    serializer_class = DefinitionSerializer

    def get(self, request, pool_id):
        """Retrieve the definition associate with a pool."""
        pool_id = self.kwargs.get('pool_id')
        pool = get_object_or_404(Pool, pk=pool_id)
        serializer = self.get_serializer(pool.definition)
        return Response(serializer.data)


class PoolLockList(mixins.ListModelMixin, generics.GenericAPIView):
    serializer_class = serializers.PoolLockSerializer

    def get_queryset(self):
        pool_id = self.kwargs.get('pool_id')
        # check that given pool exists
        get_object_or_404(Pool, pk=pool_id)
        return PoolLock.objects.filter(pool=pool_id)

    def post(self, request, pool_id):
        """Lock given pool."""
        pool = pools.get_pool(pool_id)
        lock = pools.lock_pool(pool)
        return Response(self.serializer_class(lock).data, status=status.HTTP_201_CREATED)

    def get(self, request, *args, **kwargs):
        """List locks for given pool."""
        return self.list(request, *args, **kwargs)


class PoolLockDetail(generics.RetrieveDestroyAPIView):
    """delete: Delete given lock."""
    queryset = PoolLock.objects.all()
    lookup_url_kwarg = "lock_id"
    serializer_class = serializers.PoolLockSerializer


class PoolAllocationRequestList(generics.ListAPIView):
    """get: List Allocation Request for this pool."""
    serializer_class = serializers.AllocationRequestSerializer

    def get_queryset(self):
        pool_id = self.kwargs.get('pool_id')
        pool = get_object_or_404(Pool, pk=pool_id)
        return AllocationRequest.objects.filter(allocation_unit__in=pool.allocation_units.all())


class PoolCleanupRequestList(generics.ListAPIView):
    """get: List Cleanup Request for this pool."""
    serializer_class = serializers.CleanupRequestSerializer

    def get_queryset(self):
        pool_id = self.kwargs.get('pool_id')
        pool = get_object_or_404(Pool, pk=pool_id)
        return CleanupRequest.objects.filter(allocation_unit__in=pool.allocation_units.all())


class SandboxAllocationUnitList(mixins.ListModelMixin, generics.GenericAPIView):
    serializer_class = serializers.SandboxAllocationUnitSerializer

    def get_queryset(self):
        return SandboxAllocationUnit.objects.filter(pool_id=self.kwargs.get('pool_id'))

    # noinspection PyUnusedLocal
    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter('count', openapi.IN_QUERY,
                              description="Sandbox count parameter", type=openapi.TYPE_INTEGER),
        ],
        responses={status.HTTP_201_CREATED: serializers.SandboxAllocationUnitSerializer(many=True)})
    def post(self, request, pool_id):
        """Create Sandbox Allocation Unit.
        For each Allocation Unit the Allocation Request is created in given pool.
        If count is not specified, builds *max_size - current size*.
        Query Parameters:
        - *count:* How many sandboxes to build. Optional (defaults to max_size - current size).
        """
        pool = pools.get_pool(pool_id)
        count = request.GET.get('count')
        if count is not None:
            try:
                count = int(count)
            except ValueError:
                raise exceptions.ValidationError("Invalid parameter count: %s" % count)

        requests = pools.create_sandboxes_in_pool(pool, count=count)
        serializer = self.serializer_class(requests, many=True)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def get(self, request, *args, **kwargs):
        """Get a list of Sandbox Allocation Units."""
        return self.list(request, *args, **kwargs)

    # noinspection PyUnusedLocal
    @swagger_auto_schema(responses={status.HTTP_202_ACCEPTED:
                                    serializers.CleanupRequestSerializer(many=True)})
    def delete(self, request, pool_id):
        """Delete all Sandbox Allocation Units in pool.
        __NOTE:__ The sandboxes associated with the Allocation units cannot be locked,
        or the call fails.
        """
        pool = pools.get_pool(pool_id)
        requests = pools.delete_allocation_units(pool)
        serializer = serializers.CleanupRequestSerializer(requests, many=True)
        return Response(serializer.data, status=status.HTTP_202_ACCEPTED)


class SandboxAllocationUnitDetail(generics.RetrieveAPIView, generics.GenericAPIView):
    """get: Retrieve a Sandbox Allocation Unit."""
    serializer_class = serializers.SandboxAllocationUnitSerializer
    queryset = SandboxAllocationUnit.objects.all()
    lookup_url_kwarg = "unit_id"


class SandboxAllocationRequest(mixins.RetrieveModelMixin, generics.GenericAPIView):
    """get: Retrieve a Sandbox Allocation Request for an Allocation Unit.
    Each Allocation Unit has exactly one Allocation Request.
    (There may occur a situation where it has none, then it returns 404.)
    """
    queryset = AllocationRequest.objects.none()  # Required for DjangoModelPermissions
    serializer_class = serializers.AllocationRequestSerializer

    def get(self, request, unit_id):
        unit = get_object_or_404(SandboxAllocationUnit, pk=unit_id)
        try:
            request = unit.allocation_request
        except AttributeError:
            raise Http404
        serializer = self.get_serializer(request)
        return Response(serializer.data)


class SandboxAllocationRequestCancel(generics.GenericAPIView):
    serializer_class = serializers.AllocationRequestSerializer
    queryset = AllocationRequest.objects.all()
    lookup_url_kwarg = "request_id"

    # noinspection PyUnusedLocal
    @swagger_auto_schema(responses={status.HTTP_200_OK: serializers.serializers.Serializer()})
    def patch(self, request, unit_id, request_id):
        """Cancel given Allocation Request. Returns no data if OK (200)."""
        sandbox_destructor.cancel_allocation_request(self.get_object())
        return Response()


class SandboxAllocationRequestStageList(generics.ListAPIView):
    """get: List sandbox Allocation stages."""
    serializer_class = serializers.AllocationStageSerializer

    def get_queryset(self):
        request_id = self.kwargs.get('request_id')
        get_object_or_404(AllocationRequest, pk=request_id)  # check that given request exists
        return AllocationStage.objects.filter(request_id=request_id).select_subclasses()


class SandboxCleanupRequestList(mixins.ListModelMixin, generics.GenericAPIView):
    serializer_class = serializers.CleanupRequestSerializer

    def get_queryset(self):
        return CleanupRequest.objects.filter(allocation_unit=self.kwargs.get('unit_id'))

    def post(self, request, unit_id):
        """ Create cleanup request.."""
        unit = get_object_or_404(SandboxAllocationUnit, pk=unit_id)
        cleanup_req = sandbox_destructor.create_cleanup_request(unit)
        serializer = self.serializer_class(cleanup_req)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def get(self, request, *args, **kwargs):
        """Get a list of Sandbox Cleanup Requests."""
        return self.list(request, *args, **kwargs)


class SandboxCleanupRequestDetail(generics.RetrieveAPIView):
    """get: Retrieve a Sandbox Cleanup Request."""
    serializer_class = serializers.CleanupRequestSerializer
    queryset = CleanupRequest.objects.all()
    lookup_url_kwarg = "request_id"


class SandboxCleanupRequestStageList(generics.ListAPIView):
    """get: List sandbox Cleanup stages."""
    serializer_class = serializers.CleanupStageSerializer

    def get_queryset(self):
        request_id = self.kwargs.get('request_id')
        get_object_or_404(CleanupRequest, pk=request_id)  # check that given request exists
        return CleanupStage.objects.filter(request_id=request_id).select_subclasses()


class OpenstackAllocationStageDetail(generics.GenericAPIView):
    serializer_class = serializers.OpenstackAllocationStageSerializer
    queryset = StackAllocationStage.objects.all()
    lookup_url_kwarg = "stage_id"
    pagination_class = None

    # noinspection PyUnusedLocal
    def get(self, request, stage_id):
        """Retrieve an `openstack` stage.
        Null `status` and `status_reason` attributes mean, that stack does not have them;
        AKA it does not exist in OpenStack."""
        stage = self.get_object()
        updated = StackStageHandler().update_allocation_stage(stage)
        serializer = self.get_serializer(updated)
        return Response(serializer.data)


class OpenstackCleanupStageDetail(generics.RetrieveAPIView):
    """get: Retrieve an `openstack` Cleanup stage."""
    serializer_class = serializers.OpenstackCleanupStageSerializer
    queryset = StackCleanupStage.objects.all()
    lookup_url_kwarg = "stage_id"


class SandboxEventList(generics.ListAPIView):
    """get: List sandbox Events."""
    serializer_class = serializers.SandboxEventSerializer

    def get_queryset(self):
        unit_id = self.kwargs.get('unit_id')
        unit = get_object_or_404(SandboxAllocationUnit, pk=unit_id)
        return units.get_stack_events(unit)


class SandboxResourceList(generics.ListAPIView):
    """get: List sandbox Resources."""
    serializer_class = serializers.SandboxResourceSerializer

    def get_queryset(self):
        unit_id = self.kwargs.get('unit_id')
        unit = get_object_or_404(SandboxAllocationUnit, pk=unit_id)
        return units.get_stack_resources(unit)


#########################################
# POOLS OF SANDBOXES MANIPULATION VIEWS #
#########################################

class PoolSandboxList(generics.GenericAPIView):
    queryset = Pool.objects.all()
    serializer_class = serializers.SandboxSerializer
    lookup_url_kwarg = "pool_id"
    permission_classes = [import_string(item) | AllowReadOnViewSandbox
                          for item in settings.REST_FRAMEWORK['DEFAULT_PERMISSION_CLASSES']]

    # noinspection PyUnusedLocal
    def get(self, request, pool_id):
        """Get a list of sandboxes in given pool."""
        sb_list = pools.get_sandboxes_in_pool(self.get_object())

        page = self.paginate_queryset(sb_list)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(sb_list, many=True)
        return Response(serializer.data)


class PoolKeypairManagement(generics.RetrieveAPIView):
    """
    get: Retrieve management key-pair.
    Management keypair is the same for each sandbox in the pool.
    """
    queryset = Pool.objects.all()
    lookup_url_kwarg = "pool_id"
    serializer_class = serializers.PoolKeypairSerializer


class SandboxGetAndLock(generics.GenericAPIView):
    serializer_class = serializers.SandboxSerializer
    queryset = Sandbox.objects.all()
    lookup_url_kwarg = "pool_id"
    pagination_class = None

    @swagger_auto_schema(
         responses={status.HTTP_200_OK: serializers.SandboxSerializer()})
    def get(self, request, pool_id):
        """Get unlocked sandbox in given pool and lock it. Return 409 if all are locked."""
        pool = pools.get_pool(pool_id)
        sandbox = pools.get_unlocked_sandbox(pool)
        if not sandbox:
            return Response({'detail': 'All sandboxes are already locked.'},
                            status=status.HTTP_409_CONFLICT)
        return Response(self.serializer_class(sandbox).data)


#######################################
# SANDBOX MANIPULATION VIEWS #
#######################################

class SandboxDetail(generics.RetrieveAPIView):
    """get: Retrieve a sandbox."""
    serializer_class = serializers.SandboxSerializer
    lookup_url_kwarg = "sandbox_id"
    queryset = Sandbox.objects.all()


class SandboxLockList(mixins.ListModelMixin, generics.GenericAPIView):
    serializer_class = serializers.SandboxLockSerializer

    def get_queryset(self):
        sandbox_id = self.kwargs.get('sandbox_id')
        # check that given sandbox exists
        get_object_or_404(Sandbox, pk=sandbox_id)
        return SandboxLock.objects.filter(sandbox=sandbox_id)

    def post(self, request, sandbox_id):
        """Lock given sandbox."""
        sandbox = sandboxes.get_sandbox(sandbox_id)
        lock = sandboxes.lock_sandbox(sandbox)
        return Response(self.serializer_class(lock).data, status=status.HTTP_201_CREATED)

    def get(self, request, *args, **kwargs):
        """List locks for given sandbox."""
        return self.list(request, *args, **kwargs)


class SandboxLockDetail(generics.RetrieveDestroyAPIView):
    """delete: Delete given lock."""
    queryset = SandboxLock.objects.all()
    lookup_url_kwarg = "lock_id"
    serializer_class = serializers.SandboxLockSerializer


class SandboxKeypairUser(generics.RetrieveAPIView):
    """get: Retrieve user key-pair. It is unique for each sandbox."""
    queryset = Sandbox.objects.all()
    lookup_url_kwarg = "sandbox_id"
    serializer_class = serializers.SandboxKeypairSerializer


class SandboxTopology(generics.GenericAPIView):
    queryset = Sandbox.objects.all()
    lookup_url_kwarg = "sandbox_id"
    serializer_class = serializers.TopologySerializer
    pagination_class = None

    # noinspection PyUnusedLocal
    def get(self, request, sandbox_id):
        """Get topology data for given sandbox.
        Hosts specified as hidden are filtered out, but the network is still visible.
        __NOTE:__ this endpoint is cached indefinitely.
        So the topology can be accessed even when the sandbox is long deleted.
        """
        topology = sandboxes.Topology(self.get_object())
        topology.create()
        return Response(self.serializer_class(topology).data)


class SandboxVMDetail(generics.GenericAPIView):
    queryset = Sandbox.objects.all()
    lookup_url_kwarg = "sandbox_id"
    serializer_class = serializers.NodeSerializer

    # noinspection PyUnusedLocal
    def get(self, request, sandbox_id, vm_name):
        """Retrieve a VM info.
        Important Statuses:
        - ACTIVE (vm is active and running)
        - REBOOT (vm rebooting)
        - SUSPENDED (vm suspended)
        - ... https://developer.openstack.org/api-guide/compute/server_concepts.html#server-status
        """
        sandbox = self.get_object()
        node = nodes.get_node(sandbox, vm_name)
        return Response(serializers.NodeSerializer(node).data)

    # noinspection PyUnusedLocal
    @swagger_auto_schema(request_body=serializers.NodeActionSerializer(),
                         responses={status.HTTP_200_OK: serializers.serializers.Serializer()})
    def patch(self, request, sandbox_id, vm_name):
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
        nodes.node_action(sandbox, vm_name, action)
        return Response()


class SandboxVMConsole(generics.GenericAPIView):
    queryset = Sandbox.objects.all()
    lookup_url_kwarg = "sandbox_id"
    serializer_class = serializers.NodeConsoleSerializer
    pagination_class = None

    # noinspection PyUnusedLocal
    def get(self, request, sandbox_id, vm_name):
        """Get a console for given machine. It is active for 2 hours.
        But when the connection is active, it does not disconnect.
        """
        sandbox = self.get_object()
        console = nodes.get_console_url(sandbox, vm_name)
        return Response({'url': console})


class SandboxUserSSHConfig(APIView):
    queryset = Sandbox.objects.none()  # Required for DjangoModelPermissions

    @staticmethod
    def get(request, sandbox_id):
        """Generate SSH config for User access to this sandbox.
        Some values are user specific, the config contains placeholders for them."""
        sandbox = sandboxes.get_sandbox(sandbox_id)
        ssh_config = sandboxes.get_user_sshconfig(sandbox)
        response = HttpResponse(FileWrapper(io.StringIO(ssh_config.serialize())),
                                content_type='application/txt')
        response['Content-Disposition'] = "attachment; filename=config"
        return response


class SandboxManagementSSHConfig(APIView):
    queryset = Sandbox.objects.none()  # Required for DjangoModelPermissions

    @staticmethod
    def get(request, sandbox_id):
        """Generate SSH config for Management access to this sandbox.
        Some values are user specific, the config contains placeholders for them."""
        sandbox = sandboxes.get_sandbox(sandbox_id)
        ssh_config = sandboxes.get_management_sshconfig(sandbox)
        response = HttpResponse(FileWrapper(io.StringIO(ssh_config.serialize())),
                                content_type='application/txt')
        response['Content-Disposition'] = "attachment; filename=config"
        return response
