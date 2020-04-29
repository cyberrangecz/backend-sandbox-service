import pytest
from rest_framework.exceptions import ValidationError

from kypo.sandbox_common_lib import exceptions
from kypo.sandbox_definition_app.lib import definitions
from kypo.sandbox_definition_app.lib.definition_providers import GitlabProvider, \
    GithubCompatibleProvider, GitProvider
from kypo.sandbox_definition_app.models import Definition

pytestmark = pytest.mark.django_db


class TestCreateDefinition:
    url = 'def-url'
    rev = 'def-rev'
    name = 'def-name'

    def test_create_definition_success(self, mocker):
        mocker.patch("kypo.sandbox_definition_app.lib.definitions.DefinitionProvider")
        mocker.patch("kypo.openstack_driver.ostack_client.KypoOstackClient"
                     ".validate_topology_definition")
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
                     ".validate_topology_definition")
        mock = mocker.Mock()
        mock.configure_mock(name='def-name')
        mocker.patch("kypo.sandbox_definition_app.lib.definitions.get_definition",
                     return_value=mock)

        definitions.create_definition(url=self.url, rev=self.rev)
        with pytest.raises(ValidationError):
            definitions.create_definition(url=self.url, rev=self.rev)


class TestGetDefProvider:
    schema_to_provider = {
        'git@gitlab': GitlabProvider,
        'ssh://git@': GithubCompatibleProvider,
        'http://': GitProvider,
        'https://': GitProvider,
        'file://': GitProvider,
    }

    def test_get_def_provider_success(self, mocker):
        for url, exp_provider in self.schema_to_provider.items():
            provider = definitions.get_def_provider(url, mocker.Mock())
            assert isinstance(provider, exp_provider), url

    def test_get_def_provider_invalid(self, mocker):
        with pytest.raises(exceptions.ValidationError):
            definitions.get_def_provider('nonsense:whatever', mocker.Mock())
