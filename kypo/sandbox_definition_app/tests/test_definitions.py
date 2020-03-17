import pytest
from rest_framework.exceptions import ValidationError

from kypo.sandbox_definition_app.lib import definitions
from kypo.sandbox_definition_app.models import Definition

pytestmark = pytest.mark.django_db


class TestCreateDefinition:
    url = 'def-url'
    rev = 'def-rev'
    name = 'def-name'

    def test_create_definition_success(self, mocker):
        mocker.patch("kypo.sandbox_definition_app.lib.definitions.DefinitionProvider")
        mocker.patch("kypo.openstack_driver.ostack_client.KypoOstackClient"
                     ".validate_sandbox_definition")
        mock = mocker.Mock()
        mock.configure_mock(name='def-name')
        mocker.patch("kypo.sandbox_definition_app.lib.definitions.get_definition",
                     return_value=mock)

        definitions.create_definition(url=self.url, rev=self.rev)

        # Definition name is tested by get
        database_definition = Definition.objects.get(name=self.name)
        assert database_definition.url == self.url
        assert database_definition.rev == self.rev

    def test_create_definition_nonunique(self, mocker):
        mocker.patch("kypo.sandbox_definition_app.lib.definitions.DefinitionProvider")
        mocker.patch("kypo.openstack_driver.ostack_client.KypoOstackClient"
                     ".validate_sandbox_definition")
        mock = mocker.Mock()
        mock.configure_mock(name='def-name')
        mocker.patch("kypo.sandbox_definition_app.lib.definitions.get_definition",
                     return_value=mock)

        definitions.create_definition(url=self.url, rev=self.rev)
        with pytest.raises(ValidationError):
            definitions.create_definition(url=self.url, rev=self.rev)
