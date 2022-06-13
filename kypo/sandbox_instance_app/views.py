from wsgiref.util import FileWrapper

import structlog
from django.conf import settings
from django.http import HttpResponse, Http404
from django.contrib.auth.models import AnonymousUser
from drf_yasg2 import openapi
from drf_yasg2.utils import swagger_auto_schema
from rest_framework import status, generics
from rest_framework.response import Response
from rest_framework.views import APIView

from kypo.sandbox_common_lib import exceptions, utils
from kypo.sandbox_common_lib.utils import get_object_or_404
from kypo.sandbox_definition_app.lib import definitions
from kypo.sandbox_definition_app.serializers import DefinitionSerializer

from kypo.sandbox_instance_app import serializers
from kypo.sandbox_instance_app.lib import pools, sandboxes, nodes,\
    requests as sandbox_requests
from kypo.sandbox_instance_app.models import Pool, Sandbox, SandboxAllocationUnit, \
    AllocationRequest, CleanupRequest, SandboxLock, PoolLock
from kypo.sandbox_instance_app.lib import stage_handlers

LOG = structlog.get_logger()


@utils.add_error_responses_doc('get', [401, 403, 500])
@utils.add_error_responses_doc('post', [400, 401, 403, 404, 500])
class PoolListCreateView(generics.ListCreateAPIView):
    """
    get: Get a list of pools.
    """
    queryset = Pool.objects.all()
    serializer_class = serializers.PoolSerializer

    def post(self, request, *args, **kwargs):
        """Creates new pool.
        Also creates a new key-pair in OpenStack for this pool.
        It is then used as management key for this pool. That means that
        the management key-pair is the same for each sandbox in the pool.
        """
        created_by = None if isinstance(request.user, AnonymousUser) else request.user
        pool = pools.create_pool(request.data, created_by)
        serializer = self.serializer_class(pool)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


@utils.add_error_responses_doc('get', [401, 403, 404, 500])
@utils.add_error_responses_doc('delete', [401, 403, 404, 500])
class PoolDetailDeleteView(generics.RetrieveDestroyAPIView):
    """
    get: Retrieve a pool.
    """
    queryset = Pool.objects.all()
    serializer_class = serializers.PoolSerializer
    lookup_url_kwarg = "pool_id"

    def delete(self, request, *args, **kwargs):
        """Delete pool. The pool must be empty.
        First delete all sandboxes in given Pool.
        """
        pool = self.get_object()
        pools.delete_pool(pool)
        return Response(status=status.HTTP_204_NO_CONTENT)


@utils.add_error_responses_doc('get', [401, 403, 404, 500])
class PoolDefinitionView(generics.RetrieveAPIView):
    """
    get: Retrieve the definition associated with a pool.
    """
    queryset = Pool.objects.all()
    lookup_url_kwarg = "pool_id"
    serializer_class = DefinitionSerializer

    def get_object(self):
        return super().get_object().definition


@utils.add_error_responses_doc('get', [401, 403, 404, 500])
@utils.add_error_responses_doc('post', [400, 401, 403, 404, 500])
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
        lock = pools.lock_pool(pool)
        return Response(self.serializer_class(lock).data, status=status.HTTP_201_CREATED)


@utils.add_error_responses_doc('get', [401, 403, 404, 500])
class PoolLockDetailDeleteView(generics.RetrieveDestroyAPIView):
    """
    get: Retrieve details about given lock.
    delete: Delete given lock.
    """
    queryset = PoolLock.objects.all()
    lookup_url_kwarg = "lock_id"
    serializer_class = serializers.PoolLockSerializer


@utils.add_error_responses_doc('get', [401, 403, 404, 500])
class PoolAllocationRequestListView(generics.ListAPIView):
    """
    get: List Allocation Request for this pool.
    """
    serializer_class = serializers.AllocationRequestSerializer

    def get_queryset(self):
        pool_id = self.kwargs.get('pool_id')
        pool = get_object_or_404(Pool, pk=pool_id)
        return AllocationRequest.objects.filter(allocation_unit__in=pool.allocation_units.all())


@utils.add_error_responses_doc('get', [401, 403, 404, 500])
@utils.add_error_responses_doc('post', [400, 401, 403, 404, 500])
class PoolCleanupRequestsListCreateView(generics.ListCreateAPIView):
    """
    get: List Cleanup Requests for this pool.
    """
    serializer_class = serializers.CleanupRequestSerializer

    def get_queryset(self):
        pool_id = self.kwargs.get('pool_id')
        get_object_or_404(Pool, pk=pool_id)
        return CleanupRequest.objects.filter(allocation_unit__pool_id=pool_id)

    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter('force', openapi.IN_QUERY,
                              description="Force the deletion of sandboxes",
                              type=openapi.TYPE_BOOLEAN, default=False),
        ],
        request_body=serializers.SandboxAllocationUnitIdListSerializer)
    def post(self, request, *args, **kwargs):
        """Deletes multiple sandboxes. With an optional parameter *force*,
        it forces the deletion."""
        pool_id = kwargs.get('pool_id')
        get_object_or_404(Pool, pk=pool_id)
        pool_units = SandboxAllocationUnit.objects.filter(
             pool_id=pool_id)
        unit_ids = request.data.get('unit_ids')
        force = request.GET.get('force', 'false') == 'true'
        units_to_cleanup = SandboxAllocationUnit.objects.filter(id__in=unit_ids) if len(unit_ids) \
            else pool_units
        units_to_cleanup = [allocation_unit for allocation_unit in units_to_cleanup
                            if allocation_unit in pool_units]
        cleanup_requests = sandbox_requests.create_cleanup_requests(units_to_cleanup, force)
        serializer = serializers.CleanupRequestSerializer(cleanup_requests, many=True)
        return Response(serializer.data, status=status.HTTP_202_ACCEPTED)


@utils.add_error_responses_doc('get', [401, 403, 404, 500])
class SandboxAllocationUnitListCreateView(generics.ListCreateAPIView):
    """
    get: Get a list of Sandbox Allocation Units.
    """
    serializer_class = serializers.SandboxAllocationUnitSerializer

    def get_queryset(self):
        return SandboxAllocationUnit.objects.filter(pool_id=self.kwargs.get('pool_id'))

    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter('count', openapi.IN_QUERY,
                              description="Sandbox count parameter", type=openapi.TYPE_INTEGER),
        ],
        responses={status.HTTP_201_CREATED: serializers.SandboxAllocationUnitSerializer(many=True),
                   **{k: v for k, v in utils.ERROR_RESPONSES.items()
                      if k in [400, 401, 403, 404, 500]}})
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
        requests = pools.create_sandboxes_in_pool(pool, created_by, count=count)
        serializer = self.serializer_class(requests, many=True)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


@utils.add_error_responses_doc('get', [401, 403, 404, 500])
class SandboxAllocationUnitDetailView(generics.RetrieveAPIView):
    """get: Retrieve a Sandbox Allocation Unit."""
    serializer_class = serializers.SandboxAllocationUnitSerializer
    queryset = SandboxAllocationUnit.objects.all()
    lookup_url_kwarg = "unit_id"


@utils.add_error_responses_doc('get', [401, 403, 404, 500])
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


@utils.add_error_responses_doc('get', [401, 403, 404, 500])
class AllocationRequestDetailView(generics.RetrieveAPIView):
    """get: Retrieve a Sandbox Allocation Request."""
    queryset = AllocationRequest.objects.all()
    serializer_class = serializers.AllocationRequestSerializer
    lookup_url_kwarg = 'request_id'


@utils.add_error_responses_doc('patch', [401, 403, 404, 500])
class AllocationRequestCancelView(generics.GenericAPIView):
    serializer_class = serializers.AllocationRequestSerializer
    queryset = AllocationRequest.objects.all()
    lookup_url_kwarg = "request_id"

    @swagger_auto_schema(responses={status.HTTP_200_OK: serializers.serializers.Serializer()})
    def patch(self, request, *args, **kwargs):
        """Cancel given Allocation Request. Returns no data if OK (200)."""
        sandbox_requests.cancel_allocation_request(self.get_object())
        return Response()


@utils.add_error_responses_doc('get', [401, 403, 404, 500])
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

    def post(self, request, *args, **kwargs):
        """ Create cleanup request."""
        unit = self.get_object()
        cleanup_req = sandbox_requests.create_cleanup_request(unit)
        serializer = self.serializer_class(cleanup_req)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def delete(self, request, *args, **kwargs):
        """ Delete cleanup request. Must be finished or cancelled."""
        unit = self.get_object()
        sandbox_requests.delete_cleanup_request(unit.cleanup_request)
        return Response({}, status=status.HTTP_204_NO_CONTENT)


class SandboxAllocationStagesRestartView(generics.GenericAPIView):
    serializer_class = serializers.SandboxAllocationUnitSerializer
    queryset = SandboxAllocationUnit.objects.all()
    lookup_url_kwarg = "unit_id"

    @swagger_auto_schema(
        responses={status.HTTP_201_CREATED: serializers.SandboxAllocationUnitSerializer(),
                   **{k: v for k, v in utils.ERROR_RESPONSES.items()
                      if k in [400, 401, 403, 404, 500]}})
    def patch(self, request, *args, **kwargs):
        """
        Restart all failed sandbox allocation stages.
        """
        allocation_unit = self.get_object()
        request = sandbox_requests.restart_allocation_stages(allocation_unit)

        serializer = self.serializer_class(request)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


@utils.add_error_responses_doc('get', [401, 403, 404, 500])
class CleanupRequestDetailView(generics.RetrieveAPIView):
    """get: Retrieve a Sandbox Cleanup Request."""
    serializer_class = serializers.CleanupRequestSerializer
    queryset = CleanupRequest.objects.all()
    lookup_url_kwarg = "request_id"


@utils.add_error_responses_doc('patch', [401, 403, 404, 500])
class CleanupRequestCancelView(generics.GenericAPIView):
    serializer_class = serializers.CleanupRequestSerializer
    queryset = CleanupRequest.objects.all()
    lookup_url_kwarg = "request_id"

    @swagger_auto_schema(responses={status.HTTP_200_OK: serializers.serializers.Serializer()})
    def patch(self, request, *args, **kwargs):
        """Cancel given Cleanup Request. Returns no data if OK (200)."""
        sandbox_requests.cancel_cleanup_request(self.get_object())
        return Response()


@utils.add_error_responses_doc('get', [401, 403, 404, 500])
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


@utils.add_error_responses_doc('get', [401, 403, 404, 500])
class TerraformCleanupStageDetailView(generics.RetrieveAPIView):
    """get: Retrieve an `openstack` Cleanup stage."""
    serializer_class = serializers.TerraformCleanupStageSerializer
    queryset = CleanupRequest.objects.all()
    lookup_url_kwarg = 'request_id'

    def get_object(self):
        request = super().get_object()
        return request.stackcleanupstage


class TerraformAllocationStageOutputListView(generics.ListAPIView):
    serializer_class = serializers.AllocationTerraformOutputSerializer

    def get_queryset(self):
        request_id = self.kwargs.get('request_id')
        request = get_object_or_404(AllocationRequest, pk=request_id)
        return request.stackallocationstage.terraform_outputs.all()


#########################################
# POOLS OF SANDBOXES MANIPULATION VIEWS #
#########################################

@utils.add_error_responses_doc('get', [401, 403, 404, 500])
class PoolSandboxListView(generics.ListAPIView):
    serializer_class = serializers.SandboxSerializer

    def get_queryset(self):
        pool_id = self.kwargs.get('pool_id')
        pool = get_object_or_404(Pool, pk=pool_id)
        alloc_unit_ids = [unit.id for unit in pool.allocation_units.all()]
        return Sandbox.objects.filter(allocation_unit_id__in=alloc_unit_ids)


class SandboxGetAndLockView(generics.RetrieveAPIView):
    serializer_class = serializers.SandboxSerializer
    queryset = Sandbox.objects.all()  # To allow trainee to access training run!
    lookup_url_kwarg = "pool_id"

    @swagger_auto_schema(
        responses={status.HTTP_409_CONFLICT:
                   openapi.Response('No free sandboxes; all sandboxes are locked.',
                                    utils.ErrorSerilizer()),
                   **{k: v for k, v in utils.ERROR_RESPONSES.items() if
                      k in [400, 401, 403, 404, 500]}})
    def get(self, request, *args, **kwargs):
        """Get unlocked sandbox in given pool and lock it. Return 409 if all are locked."""
        pool_id = self.kwargs.get('pool_id')
        pool = get_object_or_404(Pool, id=pool_id)
        sandbox = pools.get_unlocked_sandbox(pool)
        if not sandbox:
            return Response({'detail': 'All sandboxes are already locked.'},
                            status=status.HTTP_409_CONFLICT)
        return Response(self.serializer_class(sandbox).data)


#######################################
# SANDBOX MANIPULATION VIEWS #
#######################################

@utils.add_error_responses_doc('get', [401, 403, 404, 500])
class SandboxDetailView(generics.RetrieveAPIView):
    """get: Retrieve a sandbox."""
    serializer_class = serializers.SandboxSerializer
    lookup_url_kwarg = "sandbox_id"
    queryset = Sandbox.objects.all()


@utils.add_error_responses_doc('get', [401, 403, 404, 500])
@utils.add_error_responses_doc('post', [400, 401, 403, 404, 500])
class SandboxLockListCreateView(generics.ListCreateAPIView):
    serializer_class = serializers.SandboxLockSerializer
    """get: List locks for given sandbox."""

    def get_queryset(self):
        sandbox_id = self.kwargs.get('sandbox_id')
        get_object_or_404(Sandbox, pk=sandbox_id)
        return SandboxLock.objects.filter(sandbox=sandbox_id)

    def post(self, request, *args, **kwargs):
        """Lock given sandbox."""
        sandbox = sandboxes.get_sandbox(kwargs.get('sandbox_id'))
        lock = sandboxes.lock_sandbox(sandbox)
        return Response(self.serializer_class(lock).data, status=status.HTTP_201_CREATED)


@utils.add_error_responses_doc('get', [401, 403, 404, 500])
class SandboxLockDetailDestroyView(generics.RetrieveDestroyAPIView):
    """delete: Delete given lock."""
    queryset = SandboxLock.objects.all()
    lookup_url_kwarg = "lock_id"
    serializer_class = serializers.SandboxLockSerializer


@utils.add_error_responses_doc('get', [401, 403, 404, 500])
class SandboxTopologyView(generics.RetrieveAPIView):
    """
    get: Get topology data for given sandbox.
    Hosts specified as hidden are filtered out, but the network is still visible.
    """
    queryset = Sandbox.objects.all()
    lookup_url_kwarg = "sandbox_id"
    serializer_class = serializers.TopologySerializer

    def get_object(self):
        return sandboxes.get_sandbox_topology(super().get_object())


@utils.add_error_responses_doc('get', [401, 403, 404, 500])
class SandboxVMDetailView(generics.GenericAPIView):
    queryset = Sandbox.objects.all()
    lookup_url_kwarg = "sandbox_id"
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

    @swagger_auto_schema(request_body=serializers.NodeActionSerializer(),
                         responses={status.HTTP_200_OK: serializers.serializers.Serializer(),
                         **{k: v for k, v in utils.ERROR_RESPONSES.items() if
                            k in [400, 401, 403, 404, 500]}})
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


@utils.add_error_responses_doc('get', [401, 403, 404, 500])
class SandboxVMConsoleView(APIView):
    queryset = Sandbox.objects.none()

    # noinspection PyMethodMayBeStatic
    def get(self, request, *args, **kwargs):
        """Get a console for given machine. It is active for 2 hours.
        But when the connection is active, it does not disconnect.
        """
        sandbox = sandboxes.get_sandbox(kwargs.get('sandbox_id'))
        console = nodes.get_console_url(sandbox, kwargs.get('vm_name'))
        return Response({'url': console})


@utils.add_error_responses_doc('get', [401, 403, 404, 500])
class SandboxUserSSHAccessView(APIView):
    queryset = Sandbox.objects.none()

    # noinspection PyMethodMayBeStatic
    def get(self, request, *args, **kwargs):
        """Generate SSH config for User access to this sandbox.
        Some values are user specific, the config contains placeholders for them."""
        sandbox = sandboxes.get_sandbox(kwargs.get('sandbox_id'))
        in_memory_zip_file = sandboxes.get_user_ssh_access(sandbox)
        response = HttpResponse(FileWrapper(in_memory_zip_file),
                                content_type='application/zip')
        response['Content-Disposition'] = "attachment; filename=ssh-access.zip"
        return response


@utils.add_error_responses_doc('get', [401, 403, 404, 500])
class SandboxManOutPortIPView(APIView):
    queryset = Sandbox.objects.none()

    # noinspection PyMethodMayBeStatic
    def get(self, request, *args, **kwargs):
        """Retrieve a man out port ip address."""
        sandbox = sandboxes.get_sandbox(kwargs.get('sandbox_id'))
        man_ip = sandboxes.get_topology_instance(sandbox).ip
        return Response({"ip": man_ip})


@utils.add_error_responses_doc('get', [401, 403, 404, 500])
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


@utils.add_error_responses_doc('get', [401, 403, 404, 500])
class SandboxConsolesView(APIView):
    queryset = Sandbox.objects.none()

    # noinspection PyMethodMayBeStatic
    def get(self, request, *args, **kwargs):
        """Retrieve spice console urls for all machines in the topology."""
        sandbox = sandboxes.get_sandbox(kwargs.get('sandbox_id'))
        topology_instance = sandboxes.get_topology_instance(sandbox)
        node_names = [host.name for host in topology_instance.get_hosts() if not host.hidden] + \
                     [router.name for router in topology_instance.get_routers()]
        consoles = {name: nodes.get_console_url(sandbox, name) for name in node_names}
        return Response(consoles)


@utils.add_error_responses_doc('get', [401, 403, 404, 500])
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
                                                  settings.KYPO_CONFIG)
            variable_names = [variable.name for variable in variables]
        except exceptions.GitError:
            pass
        return Response({"variables": variable_names})
