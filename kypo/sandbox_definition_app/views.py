import structlog
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from rest_framework import status, generics
from rest_framework.response import Response

from kypo.sandbox_common_lib import utils
from kypo.sandbox_definition_app import serializers
from kypo.sandbox_definition_app.lib import definitions
from kypo.sandbox_definition_app.lib.definition_providers import DefinitionProvider
from kypo.sandbox_definition_app.models import Definition

from kypo.sandbox_instance_app import serializers as instance_serializers
from kypo.sandbox_instance_app.lib.topology import Topology

LOG = structlog.get_logger()


@utils.add_error_responses_doc('get', [401, 403, 500])
@utils.add_error_responses_doc('post', [400, 401, 403, 500])
class DefinitionListCreateView(generics.ListCreateAPIView):
    """
    get: Retrieve a list of sandbox definitions.
    """
    queryset = Definition.objects.all()
    serializer_class = serializers.DefinitionSerializer

    def post(self, request, *args, **kwargs):
        """
        Create a new sandbox definition. Optional parameter *rev* defaults to master.
        """
        url = request.data.get('url')
        rev = request.data.get('rev', "master")
        created_by = None if isinstance(request.user, AnonymousUser) else request.user
        definition = definitions.create_definition(url, created_by, rev)
        serializer = self.serializer_class(definition)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


@utils.add_error_responses_doc('get', [401, 403, 404, 500])
@utils.add_error_responses_doc('delete', [401, 403, 404, 500])
class DefinitionDetailDeleteView(generics.RetrieveDestroyAPIView):
    """
    get: Retrieve the definition.
    delete: Delete the definition.
    There can't exist a pool associated with this definition or delete fails.
    """
    queryset = Definition.objects.all()
    serializer_class = serializers.DefinitionSerializer
    lookup_url_kwarg = "definition_id"


@utils.add_error_responses_doc('get', [401, 403, 404, 500])
class DefinitionRefsListView(generics.ListAPIView):
    """
    get: Retrieve a list of definition refs (branches and tags).
    """
    serializer_class = serializers.DefinitionRevSerializer

    def get_queryset(self):
        def_id = self.kwargs.get('definition_id')
        definition = utils.get_object_or_404(Definition, pk=def_id)
        provider: DefinitionProvider = definitions.get_def_provider(definition.url,
                                                                    settings.KYPO_CONFIG)
        return provider.get_refs()


@utils.add_error_responses_doc('get', [401, 403, 404, 500])
class DefinitionTopologyView(generics.RetrieveAPIView):
    """
    get: Retrieve topology visualisation data from TopologyDefinition
    """
    queryset = Definition.objects.all()
    lookup_url_kwarg = "definition_id"
    serializer_class = instance_serializers.TopologySerializer

    def get_object(self):
        definition = super().get_object()
        topology_definition = definitions.get_definition(definition.url, definition.rev,
                                                         settings.KYPO_CONFIG)
        client = utils.get_terraform_client()
        return Topology(client.get_topology_instance(topology_definition))
