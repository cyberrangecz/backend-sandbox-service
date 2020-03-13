from django.shortcuts import get_object_or_404
from rest_framework import status, generics, mixins
from rest_framework.response import Response
from django.conf import settings

from kypo.sandbox_definition_app.lib.definition_providers import GitlabProvider

from kypo.sandbox_definition_app.models import Definition
from kypo.sandbox_definition_app import serializers
from kypo.sandbox_definition_app.lib import definitions


class DefinitionList(mixins.ListModelMixin,
                     generics.GenericAPIView):
    queryset = Definition.objects.all()
    serializer_class = serializers.DefinitionSerializer

    def get(self, request, *args, **kwargs):
        """Retrieve list of sandbox definitions."""
        return self.list(request, *args, **kwargs)

    def post(self, request):
        """
        Create new sandbox definition. Optional parameter *rev* defaults to master.
        """
        url = request.data.get('url')
        rev = request.data.get('rev', "master")
        definition = definitions.create_definition(url, rev)
        serializer = self.serializer_class(definition)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class DefinitionDetail(generics.RetrieveDestroyAPIView):
    """
    get: Retrieve the definition.

    delete: Delete the definition.
    There can't exist a pool associated with this definition or delete fails.
    """
    queryset = Definition.objects.all()
    serializer_class = serializers.DefinitionSerializer
    lookup_url_kwarg = "definition_id"


class DefinitionRefs(generics.ListAPIView):
    """
    get: Retrieve list of definition refs (branches and tags).
    """
    serializer_class = serializers.DefinitionRevSerializer

    def get_queryset(self):
        def_id = self.kwargs.get('definition_id')
        definition = get_object_or_404(Definition, pk=def_id)  # check that given request exists
        return GitlabProvider(definition.url, settings.KYPO_CONFIG.git_access_token).get_refs()
