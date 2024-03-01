import pytest
import io
from yamlize import YamlizingError

from crczp.sandbox_common_lib.crczp_config import CrczpConfiguration
from crczp.sandbox_definition_app.lib import definitions
from crczp.sandbox_definition_app.lib.definition_providers import GitlabProvider
from crczp.sandbox_definition_app.models import Definition
from crczp.sandbox_common_lib import exceptions

pytestmark = pytest.mark.django_db


class TestCreateDefinition:
    URL = 'https://gitlab.example.com/my-repo.git'
    REV = 'def-rev'
    NAME = 'def-name'

    @pytest.fixture(autouse=True)
    def setup(self, mocker):
        mocker.patch("crczp.sandbox_definition_app.lib.definitions.DefinitionProvider")
        mocker.patch("crczp.terraform_driver.CrczpTerraformClient.validate_topology_definition")

    @pytest.fixture
    def topology_definition(self, mocker):
        definition = mocker.Mock()
        definition.name = self.NAME
        mocker.patch("crczp.sandbox_definition_app.lib.definitions.get_definition",
                     return_value=definition)
        return definition

    def test_create_definition(self, mocker, topology_definition, created_by):
        mocker.patch("crczp.sandbox_definition_app.lib.definitions.validate_topology_definition")
        definitions.create_definition(url=self.URL, rev=self.REV, created_by=created_by)

        # Definition name is tested by get
        database_definition = Definition.objects.get(name=self.NAME)
        assert database_definition.url == self.URL
        assert database_definition.rev == self.REV

    def test_create_definition_nonunique(self, mocker, topology_definition, created_by):
        mocker.patch("crczp.sandbox_definition_app.lib.definitions.validate_topology_definition")
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
            assert host.base_box.image == 'debian-12-x86_64'
            assert host.flavor == 'standard.small'

        for router in topology_definition.routers:
            assert router.base_box.image == 'debian-12-x86_64'
            assert router.flavor == 'standard.small'

    def test_load_definition_invalid_definition(self, mocker, topology_definition_stream):
        topology_definition = mocker \
            .patch("crczp.sandbox_definition_app.lib.definitions.TopologyDefinition")
        topology_definition.load.side_effect = YamlizingError('exception-text')

        with pytest.raises(exceptions.ValidationError):
            definitions.load_definition(topology_definition_stream)


class TestGetDefinition:
    CFG = CrczpConfiguration()

    def test_get_definition(self, mocker):
        topology_provider = mocker.MagicMock()
        topology_provider.get_file.return_value = "test1"
        mocker.patch("crczp.sandbox_definition_app.lib.definitions.get_def_provider",
                     return_value=topology_provider)
        mocker.patch("crczp.sandbox_definition_app.lib.definitions.io.StringIO",
                     return_value="test2")
        mock_load_definition = mocker.patch("crczp.sandbox_definition_app.lib.definitions.load_definition",
                                            return_value="test3")
        mocker.patch("crczp.sandbox_definition_app.lib.definitions.validate_topology_definition",
                     return_value="")
        assert definitions.get_definition('url', 'rev', self.CFG) == "test3"
        mock_load_definition.assert_called_with(definitions.io.StringIO("test1"))

    def test_get_definition_file_not_found(self, mocker):
        topology_provider = mocker.MagicMock()
        topology_provider.get_file.side_effect = exceptions.GitError("file not found error")
        mocker.patch("crczp.sandbox_definition_app.lib.definitions.get_def_provider",
                     return_value=topology_provider)
        with pytest.raises(exceptions.GitError):
            definitions.get_definition('url', 'rev', self.CFG)


class TestGetDefProvider:
    def test_get_def_provider_gitlab(self):
        url_git = 'https://gitlab.com/crczp/backend-python/sandbox-service.git'
        cfg_git = CrczpConfiguration()
        assert isinstance(definitions.get_def_provider(url_git, cfg_git),
                          GitlabProvider)


class TestTopologyDefinitionValidation:
    @pytest.mark.skip(reason="fix for this implemented in issue 291")
    def test_incorrect_image_name(self, get_terraform_client, correct_topology):
        print(correct_topology)
        bad_topology = correct_topology.replace("image: debian", "image: debn", 1)
        stream = io.StringIO(bad_topology)
        definition = definitions.load_definition(stream)

        with pytest.raises(exceptions.ValidationError):
            definitions.validate_topology_definition(definition)

    @pytest.mark.parametrize('name, raises',
                             [
                                 ("First-is-not-lower-case12", True),
                                 ("first-is-lower-case12", False),
                                 ("invalid_character", True),
                                 ("-cannot-be-first", True),
                                 ("cAPITAL-LETTERS-ok", False),
                                 ("okay-name-without-numbers", False),
                                 ("2-number-cannot-be-first", True)
                             ])
    def test_definition_name_validness(self, get_terraform_client, name, raises, correct_topology):
        new_topology = correct_topology.replace("sandbox-definition", name, 1)
        stream = io.StringIO(new_topology)

        if raises:
            with pytest.raises(exceptions.ValidationError):
                definitions.load_definition(stream)
        else:
            definition = definitions.load_definition(stream)
            definitions.validate_topology_definition(definition)

    def test_unique_host_network_router_names(self, get_terraform_client, correct_topology):
        new_topology = (correct_topology
                        .replace("- name: deb", "- name: same-name", 1)
                        .replace("- name: router", "- name: same-name", 1)
                        .replace("- name: switch", "- name: same-name", 1))
        stream = io.StringIO(new_topology)
        with pytest.raises(exceptions.ValidationError):
            definitions.load_definition(stream)

    def test_unique_host_network_names(self, get_terraform_client, correct_topology):
        new_topology = (correct_topology
                        .replace("- name: deb", "- name: same-name", 1)
                        .replace("- name: router", "- name: same-name", 1))
        stream = io.StringIO(new_topology)
        with pytest.raises(exceptions.ValidationError):
            definitions.load_definition(stream)

    @pytest.mark.parametrize('group_name', ["management", "routers", "hosts"])
    def test_redefinition_of_default_groups_fails(self, get_terraform_client, group_name, correct_topology):
        new_topology = (correct_topology.replace("- name: linux-machines", "- name: " + group_name, 1))
        stream = io.StringIO(new_topology)
        definition = definitions.load_definition(stream)

        with pytest.raises(exceptions.ValidationError):
            definitions.validate_topology_definition(definition)

    @pytest.mark.parametrize('group_name', ["ssh_nodes", "winrm_nodes", "user_accessible_nodes", "hidden_hosts"])
    def test_redefinition_of_default_groups_with_invalid_names_fails(self, mocker, group_name):
        """Some of the default names use underscore, which wouldn't pass the load_definition function.
        To test if the redefinition fails, we need to bypass the load_definition function."""

        hosts_group = mocker.Mock()
        hosts_group.name = group_name

        topology_definition = mocker.Mock()
        topology_definition.name = "name"
        topology_definition.groups = [hosts_group]
        mocker.patch("crczp.sandbox_definition_app.lib.definitions.get_definition",
                     return_value=topology_definition)

        with pytest.raises(exceptions.ValidationError):
            definitions.validate_topology_definition(topology_definition)
