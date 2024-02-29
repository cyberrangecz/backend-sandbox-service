import pytest
from yamlize import YamlizingError


from kypo.sandbox_common_lib.kypo_config import KypoConfiguration, GitType
from kypo.sandbox_definition_app.lib import definitions
from kypo.sandbox_definition_app.lib.definition_providers import InternalGitProvider, GitlabProvider
from kypo.sandbox_definition_app.models import Definition
from kypo.sandbox_common_lib import exceptions

pytestmark = pytest.mark.django_db


class TestCreateDefinition:
    URL = 'def-url'
    REV = 'def-rev'
    NAME = 'def-name'

    @pytest.fixture(autouse=True)
    def setup(self, mocker):
        mocker.patch("kypo.sandbox_definition_app.lib.definitions.DefinitionProvider")
        mocker.patch("kypo.terraform_driver.KypoTerraformClient.validate_topology_definition")

    @pytest.fixture
    def topology_definition(self, mocker):
        topology_definition = mocker.Mock()
        topology_definition.name = self.NAME
        mocker.patch("kypo.sandbox_definition_app.lib.definitions.get_definition",
                     return_value=topology_definition)
        return topology_definition

    def test_create_definition(self, mocker, topology_definition, created_by):
        mocker.patch("kypo.sandbox_definition_app.lib.definitions.validate_topology_definition")
        definitions.create_definition(url=self.URL, rev=self.REV, created_by=created_by)

        # Definition name is tested by get
        database_definition = Definition.objects.get(name=self.NAME)
        assert database_definition.url == self.URL
        assert database_definition.rev == self.REV

    def test_create_definition_nonunique(self, mocker, topology_definition, created_by):
        mocker.patch("kypo.sandbox_definition_app.lib.definitions.validate_topology_definition")
        definitions.create_definition(url=self.URL, rev=self.REV, created_by=created_by)
        with pytest.raises(exceptions.ValidationError):
            definitions.create_definition(url=self.URL, rev=self.REV, created_by=created_by)

    def test_create_definition_invalid_hosts_group(self, mocker, topology_definition, created_by):
        hosts_group = mocker.Mock()
        hosts_group.name = 'hidden_hosts'
        topology_definition.groups = [hosts_group]
        with pytest.raises(exceptions.ValidationError):
            definitions.create_definition(url=self.URL, rev=self.REV, created_by=created_by)


class TestLoadDefinition:
    def test_load_definition(self, topology_definition_stream):
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

        with pytest.raises(exceptions.ValidationError):
            definitions.load_definition(topology_definition_stream)


class TestGetDefinition:
    CFG = KypoConfiguration(git_providers={'http://localhost.lan:8081': 'no-token'})

    def test_get_definition(self, mocker):
        topology_provider = mocker.MagicMock()
        topology_provider.get_file.return_value = "test1"
        mocker.patch("kypo.sandbox_definition_app.lib.definitions.get_def_provider",
                     return_value=topology_provider)
        mocker.patch("kypo.sandbox_definition_app.lib.definitions.io.StringIO",
                     return_value="test2")
        mocker.patch("kypo.sandbox_definition_app.lib.definitions.load_definition",
                     return_value="test3")
        assert definitions.get_definition('url', 'rev', self.CFG) == "test3"
        definitions.load_definition.assert_called_with(definitions.io.StringIO("test1"))

    def test_get_definition_file_not_found(self, mocker):
        topology_provider = mocker.MagicMock()
        topology_provider.get_file.side_effect = exceptions.GitError("file not found error")
        mocker.patch("kypo.sandbox_definition_app.lib.definitions.get_def_provider",
                     return_value=topology_provider)
        with pytest.raises(exceptions.GitError):
            definitions.get_definition('url', 'rev', self.CFG)


class TestGetDefProvider:
    def test_get_def_provider_internal(self):
        url_internal = 'https://localhost.lan:/repos/nested-folder/myrepo.git'
        cfg_internal = KypoConfiguration(git_providers={'http://localhost.lan:8081': 'no-token'})
        assert isinstance(definitions.get_def_provider(url_internal, cfg_internal),
                          InternalGitProvider)

    def test_get_def_provider_gitlab(self):
        url_git = 'https://gitlab.com/kypo-crp/backend-python/kypo-sandbox-service.git'
        cfg_git = KypoConfiguration(git_providers={'https://gitlab.com:8081': "not-token"})
        assert isinstance(definitions.get_def_provider(url_git, cfg_git),
                          GitlabProvider)
