import structlog
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.utils.decorators import method_decorator
from rest_framework import status, generics
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiRequest

from generator.var_generator import generate

from crczp.sandbox_common_lib import utils, exceptions
from crczp.sandbox_common_lib.swagger_typing import SandboxDefinitionSerializer, DefinitionRequestSerializer
from crczp.sandbox_definition_app import serializers
from crczp.sandbox_definition_app.lib import definitions
from crczp.sandbox_definition_app.lib.definition_providers import DefinitionProvider
from crczp.sandbox_definition_app.models import Definition

from crczp.sandbox_instance_app import serializers as instance_serializers
from crczp.sandbox_instance_app.lib import sandboxes
from crczp.sandbox_instance_app.lib.topology import Topology

LOG = structlog.get_logger()

COMMON_RESPONSE_PATTERNS = {
    401: OpenApiResponse(description='Unauthorized'),
    403: OpenApiResponse(description='Forbidden'),
    404: OpenApiResponse(description='Not Found'),
    500: OpenApiResponse(description='Internal Server Error')
}

@extend_schema(
    methods=["GET"],
    responses={
        200: OpenApiResponse(description='List of Sandbox Definitions', response=SandboxDefinitionSerializer),
        **{k: v for k, v in utils.ERROR_RESPONSES.items()
           if k in [401, 403, 500]}
    }
)
class DefinitionListCreateView(generics.ListCreateAPIView):
    """
    get: Retrieve a list of sandbox definitions.
    """
    queryset = Definition.objects.all()
    serializer_class = serializers.DefinitionSerializer

    @extend_schema(
        request=OpenApiRequest(DefinitionRequestSerializer),
        responses={
            201:  OpenApiResponse(response=SandboxDefinitionSerializer),
            **{k: v for k, v in utils.ERROR_RESPONSES.items()
               if k in [400, 401, 403, 500]}
        }
    )
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


@extend_schema(
    methods=["GET"],
    responses={200: SandboxDefinitionSerializer, **COMMON_RESPONSE_PATTERNS}
)
@extend_schema(
    methods=["DELETE"],
    responses={**COMMON_RESPONSE_PATTERNS}
)
class DefinitionDetailDeleteView(generics.RetrieveDestroyAPIView):
    """
    get: Retrieve the definition.
    delete: Delete the definition.
    There can't exist a pool associated with this definition or delete fails.
    """
    queryset = Definition.objects.all()
    serializer_class = serializers.DefinitionSerializer
    lookup_url_kwarg = "definition_id"


@extend_schema(
    methods=["GET"],
    responses={
        200: OpenApiResponse(description='List of Definition Refs',
                              response=serializers.DefinitionSerializer(many=True)),
        **COMMON_RESPONSE_PATTERNS
    }
)
class DefinitionRefsListView(generics.ListAPIView):
    """
    get: Retrieve a list of definition refs (branches and tags).
    """
    serializer_class = serializers.DefinitionRevSerializer

    def get_queryset(self):
        def_id = self.kwargs.get('definition_id')
        definition = utils.get_object_or_404(Definition, pk=def_id)
        provider: DefinitionProvider = definitions.get_def_provider(definition.url,
                                                                    settings.CRCZP_CONFIG)
        return provider.get_refs()


@extend_schema(
    methods=["GET"],
    responses={
        200: instance_serializers.TopologySerializer(many=True),
        **COMMON_RESPONSE_PATTERNS
    }
)
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
                                                         settings.CRCZP_CONFIG)
        containers = definitions.get_containers(definition.url, definition.rev,
                                                settings.CRCZP_CONFIG)
        client = utils.get_terraform_client()
        return Topology(client.get_topology_instance(topology_definition, containers))


@extend_schema(
    methods=["POST"],
    responses={
        201: serializers.LocalVariableSerializer(many=True),
        **COMMON_RESPONSE_PATTERNS
    }
)
class LocalSandboxVariablesView(generics.CreateAPIView):
    queryset = Definition.objects.all()
    lookup_url_kwarg = "definition_id"
    serializer_class = serializers.LocalSandboxVariablesSerializer

    def post(self, request, *args, **kwargs):
        """Generate variables for local sandboxes, send it to answers-storage."""
        user_id = request.data.get('user_id')
        access_token = request.data.get('access_token')

        definition = self.get_object()
        variables = definitions.get_variables(definition.url, definition.rev, settings.CRCZP_CONFIG)
        generate(variables, user_id)
        sandboxes.post_answers(user_id, access_token, variables)

        serialized_variables = serializers.LocalVariableSerializer(variables, many=True)
        return Response(serialized_variables.data)


@extend_schema(
    methods=["GET"],
    responses={200: OpenApiResponse(description='Variables List'), **COMMON_RESPONSE_PATTERNS}
)
class DefinitionVariablesView(APIView):
    queryset = Definition.objects.none()

    # noinspection PyMethodMayBeStatic
    def get(self, request, *args, **kwargs):
        """Retrieve APG variables from TopologyDefinition, empty list if variables.yml was not
        found."""
        definition = utils.get_object_or_404(Definition, pk=kwargs.get('definition_id'))
        variable_names = []
        try:
            variables = definitions.get_variables(definition.url, definition.rev, settings.CRCZP_CONFIG)
            variable_names = [variable.name for variable in variables]
        except exceptions.GitError:
            pass
        return Response({"variables": variable_names})
