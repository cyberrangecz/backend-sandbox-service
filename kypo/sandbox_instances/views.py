"""
<h2>Specification of REST responses</h2>

<b>Success JSON</b>
<pre>
{
    Requested data or empty if no data requested.
}
</pre>

<b>Error JSON</b>
<pre>
{
    detail: error message,
    parameters: {
        Dictionary of call parameters
        name: value
    }
}
</pre>
"""
import structlog
import io
from django.http import HttpResponse
from django.utils.module_loading import import_string
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework.response import Response
from rest_framework import status, generics, mixins
from rest_framework.views import APIView
from django.conf import settings
from wsgiref.util import FileWrapper
from rest_framework.generics import get_object_or_404

from ..common import exceptions
from ..common.permissions import AllowReadOnViewSandbox

from . import serializers
from .services import pool_service, sandbox_service, node_service,\
    sandbox_creator, sandbox_destructor
from .models import Pool, Sandbox, SandboxAllocationUnit, AllocationRequest

# Create logger and configure logging
LOG = structlog.get_logger()


class PoolList(generics.ListAPIView):
    """Class for pools management.

    get: Get a list of pools.
    """
    queryset = Pool.objects.all()
    serializer_class = serializers.PoolSerializer

    @staticmethod
    def post(request):
        """Creates new pool."""
        pool = pool_service.create_pool(request.data)
        serializer = serializers.PoolSerializer(pool)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class PoolDetail(mixins.RetrieveModelMixin,
                 mixins.DestroyModelMixin,
                 generics.GenericAPIView):
    """Class for managing single pool"""
    queryset = Pool.objects.all()
    serializer_class = serializers.PoolSerializer
    lookup_url_kwarg = "pool_id"

    def get(self, request, *args, **kwargs):
        """Retrieve a pool."""
        return self.retrieve(request, *args, **kwargs)

    def delete(self, request, pool_id):
        """Delete pool. The pool must be empty. First delete all sandboxes in given Pool.
        """
        pool = self.get_object()
        pool_service.delete_pool(pool)
        return Response(status=status.HTTP_204_NO_CONTENT)


class SandboxAllocationUnitList(mixins.ListModelMixin, generics.GenericAPIView):
    """Class for create-request management"""
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
        """
        Build sandboxes in given pool. If count is not specified, builds *max_size - current size*.
        Query Parameters:
        - *count:* How many sandboxes to build. Optional (defaults to max_size - current size).
        """
        pool = pool_service.get_pool(pool_id)
        count = request.GET.get('count')
        if count is not None:
            try:
                count = int(count)
            except ValueError:
                raise exceptions.ValidationError("Invalid parameter count: %s" % count)

        requests = pool_service.create_sandboxes_in_pool(pool, count=count)
        serializer = self.serializer_class(requests, many=True)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def get(self, request, *args, **kwargs):
        """Get a list of Sandbox Create Requests."""
        return self.list(request, *args, **kwargs)


# TODO: implement in services
class SandboxAllocationUnitDetail(generics.DestroyAPIView, generics.GenericAPIView):
    """Class for create-request management"""
    serializer_class = serializers.SandboxAllocationUnitSerializer
    queryset = SandboxAllocationUnit.objects.all()
    lookup_url_kwarg = "allocation_unit_id"


# TODO: viewset?
class SandboxAllocationRequestDetail(generics.RetrieveAPIView):
    serializer_class = serializers.AllocationRequestSerializer
    queryset = SandboxAllocationUnit.objects.all()
    lookup_url_kwarg = "allocation_unit_id"

#
# class SandboxDeleteRequestList(mixins.ListModelMixin, generics.GenericAPIView):
#     """Class for delete-request management"""
#     serializer_class = serializers.SandboxDeleteRequestSerializer
#
#     def get_queryset(self):
#         return SandboxDeleteRequest.objects.filter(pool_id=self.kwargs.get('pool_id'))
#
#     # noinspection PyUnusedLocal
#     @swagger_auto_schema(
#         responses={status.HTTP_201_CREATED: serializers.SandboxDeleteRequestSerializer()})
#     def post(self, request, sandbox_id):
#         """ Delete given Sandbox."""
#         create_request = SandboxCreateRequest.objects.get(pk=sandbox_id)
#
#         del_request = sandbox_destructor.delete_sandbox_request(create_request)
#         serializer = self.serializer_class(del_request)
#         return Response(serializer.data, status=status.HTTP_201_CREATED)
#
#     def get(self, request, *args, **kwargs):
#         """Get a list of Sandbox Delete Requests."""
#         return self.list(request, *args, **kwargs)


class PoolCreateRequestStageList(generics.ListAPIView):
    """
    Class for managing create stages.

    get: List sandbox create stages.
    """
    serializer_class = serializers.SandboxStageSerializer

    def get_queryset(self):
        request_id = self.kwargs.get('request_id')
        get_object_or_404(SandboxCreateRequest, pk=request_id)  # check that given request exists
        return Stage.objects.filter(request_id=request_id).select_subclasses()


class OpenstackStageDetail(generics.GenericAPIView):
    serializer_class = serializers.OpenstackStageSerializer
    queryset = StackCreateStage.objects.all()
    lookup_url_kwarg = "stage_id"

    # noinspection PyUnusedLocal
    def get(self, request, stage_id):
        """Retrieve an openstack stage."""
        stage = self.get_object()
        updated = sandbox_creator.StackCreateStageManager().update_stage(stage)
        serializer = self.get_serializer(updated)
        return Response(serializer.data)


class BootstrapStageDetail(generics.RetrieveAPIView):
    """
    get: Retrieve a bootstrap stage.
    """
    serializer_class = serializers.BootstrapStageSerializer
    queryset = BootstrapStage.objects.all()
    lookup_url_kwarg = "stage_id"


class OpenstackStageEventList(generics.GenericAPIView):
    """Class for managing Sandbox events"""
    queryset = StackCreateStage.objects.all()
    lookup_url_kwarg = "stage_id"
    serializer_class = serializers.SandboxEventSerializer
    pagination_class = None

    # noinspection PyUnusedLocal
    @swagger_auto_schema(responses={status.HTTP_200_OK: serializers.SandboxEventSerializer(many=True)})
    def get(self, request, stage_id):
        """Retrieve list of sandbox events."""
        manager = sandbox_creator.StackCreateStageManager()
        events = manager.get_events(self.get_object())
        return Response(self.serializer_class(events, many=True).data)


class OpenstackStageResourceList(generics.GenericAPIView):
    """Class for managing Sandbox resources"""
    queryset = StackCreateStage.objects.all()
    lookup_url_kwarg = "stage_id"
    serializer_class = serializers.SandboxResourceSerializer
    pagination_class = None

    # noinspection PyUnusedLocal
    @swagger_auto_schema(responses={status.HTTP_200_OK: serializers.SandboxResourceSerializer(many=True)})
    def get(self, request, stage_id):
        """Retrieve list of sandbox resources."""
        manager = sandbox_creator.StackCreateStageManager()
        resources = manager.get_resources(self.get_object())
        return Response(self.serializer_class(resources, many=True).data)


#########################################
# POOLS OF SANDBOXES MANIPULATION VIEWS #
#########################################

class PoolSandboxList(generics.GenericAPIView):
    """Class for sandboxes management"""
    queryset = Pool.objects.all()
    serializer_class = serializers.SandboxSerializer
    lookup_url_kwarg = "pool_id"
    permission_classes = [import_string(item) | AllowReadOnViewSandbox
                          for item in settings.REST_FRAMEWORK['DEFAULT_PERMISSION_CLASSES']]

    # noinspection PyUnusedLocal
    def get(self, request, pool_id):
        """Get a list of sandboxes in given pool."""
        sandboxes = pool_service.get_sandboxes_in_pool(self.get_object())

        page = self.paginate_queryset(sandboxes)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(sandboxes, many=True)
        return Response(serializer.data)


class PoolKeypairManagement(generics.RetrieveAPIView):
    """Class for managing management key-pairs

    get: Retrieve management key-pair.
    """
    queryset = Pool.objects.all()
    lookup_url_kwarg = "pool_id"
    serializer_class = serializers.PoolKeypairSerializer


#######################################
# SANDBOX MANIPULATION VIEWS #
#######################################

class SandboxDetail(generics.GenericAPIView):
    """Class for managing single sandbox"""
    serializer_class = serializers.SandboxSerializer
    queryset = Sandbox.objects.none()  # Required for DjangoModelPermissions

    @staticmethod
    def get(request, sandbox_id):
        """Retrieve sandbox."""
        sb = sandbox_service.get_sandbox(sandbox_id)
        serializer = serializers.SandboxSerializer(sb)
        return Response(serializer.data)


class SandboxLock(generics.GenericAPIView):
    """Sandbox locking management."""
    serializer_class = serializers.SandboxSerializer
    queryset = Sandbox.objects.none()  # Required for DjangoModelPermissions

    def post(self, _request, sandbox_id):
        """Lock given sandbox."""
        sandbox = sandbox_service.get_sandbox(sandbox_id)
        sandbox = sandbox_service.lock_sandbox(sandbox)
        return Response(self.serializer_class(sandbox).data)

    def delete(self, _request, sandbox_id):
        """Unlock given sandbox."""
        sandbox = sandbox_service.get_sandbox(sandbox_id)
        sandbox = sandbox_service.unlock_sandbox(sandbox)
        return Response(self.serializer_class(sandbox).data)


class SandboxKeypairUser(generics.RetrieveAPIView):
    """Class for managing user key-pairs

    get: Retrieve user key-pair.
    """
    queryset = Sandbox.objects.all()
    lookup_url_kwarg = "sandbox_id"
    serializer_class = serializers.SandboxKeypairSerializer


class SandboxTopology(APIView):
    """Class for managing topology"""
    queryset = Sandbox.objects.none()  # Required for DjangoModelPermissions

    @staticmethod
    @swagger_auto_schema(responses={status.HTTP_200_OK: serializers.TopologySerializer()})
    def get(request, sandbox_id):
        """Get topology data for given sandbox.
        Hosts specified as hidden are filtered out, but the network is still visible."""
        sandbox = sandbox_service.get_sandbox(sandbox_id)
        topology = sandbox_service.Topology(sandbox)
        topology.create()
        return Response(serializers.TopologySerializer(topology).data)


class SandboxVMDetail(APIView):
    """Class for VM manipulation"""
    queryset = Sandbox.objects.none()  # Required for DjangoModelPermissions

    @staticmethod
    @swagger_auto_schema(responses={status.HTTP_200_OK: serializers.NodeSerializer()})
    def get(request, sandbox_id, vm_name):
        """Retrieve a VM info.
        Important Statuses:
        - ACTIVE (vm is active and running)
        - REBOOT (vm rebooting)
        - SUSPENDED (vm suspended)
        - ... https://developer.openstack.org/api-guide/compute/server_concepts.html#server-status
        """
        sandbox = sandbox_service.get_sandbox(sandbox_id)
        node = node_service.get_node(sandbox, vm_name)
        return Response(serializers.NodeSerializer(node).data)

    @staticmethod
    @swagger_auto_schema(request_body=serializers.NodeActionSerializer(),
                         responses={status.HTTP_200_OK: serializers.serializers.Serializer()})
    def patch(request, sandbox_id, vm_name):
        """Perform specified action on given VM.
        Available actions are:
        - suspend
        - resume
        - reboot
        """
        sandbox = sandbox_service.get_sandbox(sandbox_id)
        try:
            action = request.data['action']
        except KeyError:
            raise exceptions.ValidationError("No action specified!")
        node_service.node_action(sandbox, vm_name, action)
        return Response()


class SandboxVMConsole(APIView):
    """Class for VM manipulation"""
    queryset = Sandbox.objects.none()  # Required for DjangoModelPermissions

    @staticmethod
    @swagger_auto_schema(responses={status.HTTP_200_OK: serializers.NodeConsoleSerializer()})
    def get(request, sandbox_id, vm_name):
        """Get a console for given machine."""
        sandbox = sandbox_service.get_sandbox(sandbox_id)
        console = node_service.get_console_url(sandbox, vm_name)
        return Response({'url': console})


class SandboxUserSSHConfig(APIView):
    """Class for managing SSH config"""
    queryset = Sandbox.objects.none()  # Required for DjangoModelPermissions

    @staticmethod
    def get(request, sandbox_id):
        """Generate SSH config for User access to this sandbox.
        Some values are user specific, the config contains placeholders for them."""
        sandbox = sandbox_service.get_sandbox(sandbox_id)
        ssh_config = sandbox_service.SandboxSSHConfigCreator(sandbox).create_user_config()
        response = HttpResponse(FileWrapper(io.StringIO(str(ssh_config))), content_type='application/txt')
        response['Content-Disposition'] = "attachment; filename=config"
        return response


class SandboxManagementSSHConfig(APIView):
    """Class for managing SSH config"""
    queryset = Sandbox.objects.none()  # Required for DjangoModelPermissions

    @staticmethod
    def get(request, sandbox_id):
        """Generate SSH config for Management access to this sandbox.
        Some values are user specific and should replaced (host usernames, …)."""
        sandbox = sandbox_service.get_sandbox(sandbox_id)
        ssh_config = sandbox_service.SandboxSSHConfigCreator(sandbox).create_management_config()
        response = HttpResponse(FileWrapper(io.StringIO(str(ssh_config))), content_type='application/txt')
        response['Content-Disposition'] = "attachment; filename=config"
        return response

