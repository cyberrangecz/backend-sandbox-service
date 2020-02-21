from rest_framework import status, generics, mixins
from rest_framework.response import Response

from kypo.sandbox_definition_app.models import Definition
from kypo.sandbox_definition_app import serializers
from kypo.sandbox_definition_app.lib import definition_service


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
        definition = definition_service.create_definition(url, rev)
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
