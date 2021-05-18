import pytest
from rest_framework.exceptions import ValidationError as RestValidationError
from yamlize import YamlizingError

from kypo.sandbox_common_lib.exceptions import ValidationError
from kypo.sandbox_definition_app.lib import definitions
from kypo.sandbox_definition_app.models import Definition

pytestmark = pytest.mark.django_db


class TestCreateDefinition:
    url = 'def-url'
    rev = 'def-rev'
    name = 'def-name'

    def test_create_definition_success(self, mocker):
        mocker.patch("kypo.sandbox_definition_app.lib.definitions.DefinitionProvider")
        mocker.patch("kypo.openstack_driver.KypoOpenStackClient.validate_topology_definition")
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
        mocker.patch("kypo.openstack_driver.KypoOpenStackClient.validate_topology_definition")
        mock = mocker.Mock()
        mock.configure_mock(name='def-name')
        mocker.patch("kypo.sandbox_definition_app.lib.definitions.get_definition",
                     return_value=mock)

        definitions.create_definition(url=self.url, rev=self.rev)
        with pytest.raises(RestValidationError):
            definitions.create_definition(url=self.url, rev=self.rev)


class TestLoadDefinition:
    def test_load_definition_success(self, topology_definition_stream):
        topology_definition = definitions.load_definition(topology_definition_stream)

        for host in topology_definition.hosts:
            assert host.base_box.image == 'debian-9-x86_64'
            assert host.flavor == 'csirtmu.tiny1x2'

        for router in topology_definition.routers:
            assert router.base_box.image == 'debian-9-x86_64'
            assert router.flavor == 'csirtmu.tiny1x2'

    def test_load_definition_invalid_definition(self, mocker, topology_definition_stream):
        topology_definition = mocker\
            .patch("kypo.sandbox_definition_app.lib.definitions.TopologyDefinition")
        topology_definition.load.side_effect = YamlizingError('exception-text')

        with pytest.raises(ValidationError):
            definitions.load_definition(topology_definition_stream)
