"""Tests for sandbox definition management."""

import copy
import io
from typing import Any

import pytest
from django.conf import settings
from django.core.cache import caches
from yamlize import YamlizingError

from crczp.sandbox_common_lib import exceptions
from crczp.sandbox_common_lib.crczp_config import CrczpConfiguration, TopologyCacheMode
from crczp.sandbox_definition_app.lib import definitions
from crczp.sandbox_definition_app.lib.definition_providers import GitlabProvider
from crczp.sandbox_definition_app.models import Definition

pytestmark = pytest.mark.django_db


class TestCreateDefinition:
    """Tests for creating sandbox definitions."""

    URL = 'https://gitlab.example.com/my-repo.git'
    GITHUB_URL = 'https://github.com/org/my-repo.git'
    REV = 'def-rev'
    NAME = 'def-name'

    @pytest.fixture(autouse=True)
    def setup(self, mocker):
        """Set up mocks for DefinitionProvider and topology validation."""
        mocker.patch('crczp.sandbox_definition_app.lib.definitions.DefinitionProvider')
        mocker.patch('crczp.terraform_driver.CrczpTerraformClient.validate_topology_definition')

    @pytest.fixture
    def topology_definition(self, mocker):
        """Return a mocked topology definition with a fixed name."""
        definition = mocker.Mock()
        definition.name = self.NAME
        mocker.patch(
            'crczp.sandbox_definition_app.lib.definitions.get_definition', return_value=definition
        )
        return definition

    def test_create_definition(self, mocker, topology_definition, created_by):  # pylint: disable=unused-argument
        """Test that a definition is created and persisted with correct fields."""
        mocker.patch('crczp.sandbox_definition_app.lib.definitions.validate_topology_definition')
        definitions.create_definition(url=self.URL, rev=self.REV, created_by=created_by)

        # Definition name is tested by get
        database_definition = Definition.objects.get(name=self.NAME)
        assert database_definition.url == self.URL
        assert database_definition.rev == self.REV

    def test_create_definition_nonunique(self, mocker, topology_definition, created_by):  # pylint: disable=unused-argument
        """Test that creating a duplicate definition raises ValidationError."""
        mocker.patch('crczp.sandbox_definition_app.lib.definitions.validate_topology_definition')
        definitions.create_definition(url=self.URL, rev=self.REV, created_by=created_by)
        with pytest.raises(exceptions.ValidationError):
            definitions.create_definition(url=self.URL, rev=self.REV, created_by=created_by)

    def test_create_definition_invalid_hosts_group(self, mocker, topology_definition, created_by):
        """Test that a definition with an invalid hosts group raises ValidationError."""
        hosts_group = mocker.Mock()
        hosts_group.name = 'hidden_hosts'
        topology_definition.groups = [hosts_group]
        with pytest.raises(exceptions.ValidationError):
            definitions.create_definition(url=self.URL, rev=self.REV, created_by=created_by)

    def test_create_definition_forwarding_disabled(self, mocker, topology_definition, created_by):
        """A definition declaring network_forwarding is rejected when the feature is off."""
        topology_definition.groups = []
        topology_definition.network_forwarding = mocker.Mock()
        mocker.patch.object(settings.CRCZP_CONFIG, 'network_forwarding_enabled', False)
        with pytest.raises(exceptions.ValidationError):
            definitions.create_definition(url=self.URL, rev=self.REV, created_by=created_by)

    def _forwarding_config(self, mocker: Any, hypervisor_cidr: str | None) -> None:
        """Swap in a copy of the app config with network forwarding enabled.

        A copy, because patching the CRCZP_CONFIG singleton in place does not survive
        teardown: its attributes are yamlize descriptors, so mock restores them by deleting
        the instance value and the class default leaks into the following tests. The nested
        ``openstack`` object is copied too — a shallow copy shares it with the singleton, so
        mutating hypervisor_cidr on it would otherwise leak across tests.
        """
        config = copy.copy(settings.CRCZP_CONFIG)
        config.network_forwarding_enabled = True
        config.openstack = copy.copy(settings.CRCZP_CONFIG.openstack)
        config.openstack.hypervisor_cidr = hypervisor_cidr
        mocker.patch.object(settings, 'CRCZP_CONFIG', config)
        mocker.patch.object(settings, 'AWS_PROVIDER_CONFIGURED', False)

    def test_create_definition_forwarding_without_hypervisor_cidr(
        self, mocker, topology_definition, created_by
    ):
        """Network forwarding on OpenStack is rejected without the hypervisor CIDR."""
        topology_definition.groups = []
        topology_definition.network_forwarding = mocker.Mock()
        self._forwarding_config(mocker, None)

        with pytest.raises(exceptions.ValidationError, match='hypervisor_cidr'):
            definitions.create_definition(url=self.URL, rev=self.REV, created_by=created_by)

    def test_create_definition_forwarding_accepted_when_configured(
        self, mocker, topology_definition, created_by
    ):
        """With the feature enabled and the hypervisor CIDR set, the definition passes."""
        topology_definition.groups = []
        topology_definition.network_forwarding = mocker.Mock()
        topology_definition.hosts = []
        topology_definition.routers = []
        # No networks, so the reserved-address check has nothing to resolve the rule against.
        topology_definition.networks = []
        self._forwarding_config(mocker, '10.99.0.0/16')
        mocker.patch('crczp.sandbox_definition_app.lib.definitions.utils.get_terraform_client')
        mocker.patch('crczp.sandbox_definition_app.lib.definitions.list_images', return_value=[])

        definitions.create_definition(url=self.URL, rev=self.REV, created_by=created_by)

        assert Definition.objects.get(name=self.NAME).url == self.URL

    def test_create_definition_fresh_import_forces_refresh(
        self, mocker, topology_definition, created_by
    ):  # pylint: disable=unused-argument
        """Test that FRESH_IMPORT mode imports a GitHub definition with force_refresh=True."""
        mocker.patch('crczp.sandbox_definition_app.lib.definitions.validate_topology_definition')
        mocker.patch.object(
            settings.CRCZP_CONFIG, 'topology_cache_mode', TopologyCacheMode.FRESH_IMPORT
        )
        definitions.create_definition(url=self.GITHUB_URL, rev=self.REV, created_by=created_by)
        definitions.get_definition.assert_any_call(
            self.GITHUB_URL, self.REV, settings.CRCZP_CONFIG, force_refresh=True
        )

    def test_create_definition_fresh_import_gitlab_does_not_force_refresh(
        self, mocker, topology_definition, created_by
    ):  # pylint: disable=unused-argument
        """Test that FRESH_IMPORT mode does not force refresh for GitLab (GitHub provider only)."""
        mocker.patch('crczp.sandbox_definition_app.lib.definitions.validate_topology_definition')
        mocker.patch.object(
            settings.CRCZP_CONFIG, 'topology_cache_mode', TopologyCacheMode.FRESH_IMPORT
        )
        definitions.create_definition(url=self.URL, rev=self.REV, created_by=created_by)
        definitions.get_definition.assert_any_call(
            self.URL, self.REV, settings.CRCZP_CONFIG, force_refresh=False
        )

    def test_create_definition_aggressive_does_not_force_refresh(
        self, mocker, topology_definition, created_by
    ):  # pylint: disable=unused-argument
        """Test that AGGRESSIVE mode imports with force_refresh=False."""
        mocker.patch('crczp.sandbox_definition_app.lib.definitions.validate_topology_definition')
        mocker.patch.object(
            settings.CRCZP_CONFIG, 'topology_cache_mode', TopologyCacheMode.AGGRESSIVE
        )
        definitions.create_definition(url=self.URL, rev=self.REV, created_by=created_by)
        definitions.get_definition.assert_any_call(
            self.URL, self.REV, settings.CRCZP_CONFIG, force_refresh=False
        )


class TestLoadDefinition:
    """Tests for loading a topology definition from a stream."""

    def test_load_definition(self, topology_definition_stream):
        """Test that a valid definition is loaded correctly."""
        topology_definition = definitions.load_definition(topology_definition_stream)

        for host in topology_definition.hosts:
            assert host.base_box.image == 'debian-12-x86_64'
            assert host.flavor == 'standard.small'

        for router in topology_definition.routers:
            assert router.base_box.image == 'debian-12-x86_64'
            assert router.flavor == 'standard.small'

    def test_load_definition_invalid_definition(self, mocker, topology_definition_stream):
        """Test that a YamlizingError during load raises ValidationError."""
        topology_definition = mocker.patch(
            'crczp.sandbox_definition_app.lib.definitions.TopologyDefinition'
        )
        topology_definition.load.side_effect = YamlizingError('exception-text')

        with pytest.raises(exceptions.ValidationError):
            definitions.load_definition(topology_definition_stream)


class TestGetDefinition:
    """Tests for fetching a definition from a git provider."""

    CFG = CrczpConfiguration()

    @pytest.fixture(autouse=True)
    def clear_topology_cache(self):
        """Isolate the process-global LocMem topology cache between tests."""
        caches['topology_cache'].clear()
        yield
        caches['topology_cache'].clear()

    def test_get_definition(self, mocker):
        """Test that get_definition fetches the file, loads and returns the definition."""
        topology_provider = mocker.MagicMock()
        topology_provider.get_file.return_value = 'test1'
        mocker.patch(
            'crczp.sandbox_definition_app.lib.definitions.get_def_provider',
            return_value=topology_provider,
        )
        mocker.patch(
            'crczp.sandbox_definition_app.lib.definitions.io.StringIO', return_value='test2'
        )
        mock_load_definition = mocker.patch(
            'crczp.sandbox_definition_app.lib.definitions.load_definition', return_value='test3'
        )
        mocker.patch(
            'crczp.sandbox_definition_app.lib.definitions.validate_topology_definition',
            return_value='',
        )
        assert definitions.get_definition('url', 'rev', self.CFG) == 'test3'
        mock_load_definition.assert_called_with(definitions.io.StringIO('test1'))

    def test_get_definition_file_not_found(self, mocker):
        """Test that a GitError is raised when the definition file is not found."""
        topology_provider = mocker.MagicMock()
        topology_provider.get_file.side_effect = exceptions.GitError('file not found error')
        mocker.patch(
            'crczp.sandbox_definition_app.lib.definitions.get_def_provider',
            return_value=topology_provider,
        )
        with pytest.raises(exceptions.GitError):
            definitions.get_definition('url', 'rev', self.CFG)

    def test_get_definition_uses_cache_when_not_forced(self, mocker):
        """Test that a cached topology is returned without fetching when not forced."""
        provider = mocker.MagicMock()
        provider.get_rev_sha.return_value = 'stable-sha'
        mocker.patch(
            'crczp.sandbox_definition_app.lib.definitions.get_def_provider',
            return_value=provider,
        )
        caches['topology_cache'].set('definition-url-rev-sha-stable-sha-topology', 'cached-def')

        assert definitions.get_definition('url', 'rev', self.CFG) == 'cached-def'
        provider.get_file.assert_not_called()

    def test_get_definition_force_refresh_bypasses_cache(self, mocker):
        """Test that force_refresh ignores the cached value, fetches fresh, and refreshes it."""
        provider = mocker.MagicMock()
        provider.get_rev_sha.return_value = 'stable-sha'
        provider.get_file.return_value = 'fresh-file'
        mocker.patch(
            'crczp.sandbox_definition_app.lib.definitions.get_def_provider',
            return_value=provider,
        )
        mocker.patch(
            'crczp.sandbox_definition_app.lib.definitions.load_definition',
            return_value='fresh-def',
        )
        mocker.patch('crczp.sandbox_definition_app.lib.definitions.validate_topology_definition')
        cache = caches['topology_cache']
        cache_key = 'definition-url-rev-sha-stable-sha-topology'
        cache.set(cache_key, 'stale-def')

        result = definitions.get_definition('url', 'rev', self.CFG, force_refresh=True)

        assert result == 'fresh-def'
        provider.get_file.assert_called_once()
        assert cache.get(cache_key) == 'fresh-def'


class TestGetDefProvider:  # pylint: disable=too-few-public-methods
    """Tests for the get_def_provider factory function."""

    def test_get_def_provider_gitlab(self):
        """Test that a Gitlab URL returns a GitlabProvider instance."""
        url_git = 'https://gitlab.com/crczp/backend-python/sandbox-service.git'
        cfg_git = CrczpConfiguration()
        assert isinstance(definitions.get_def_provider(url_git, cfg_git), GitlabProvider)


class TestTopologyDefinitionValidation:
    """Tests for topology definition validation."""

    @pytest.mark.skip(reason='fix for this implemented in issue 291')
    def test_incorrect_image_name(self, get_terraform_client, correct_topology):  # pylint: disable=unused-argument
        """Test that an invalid image name raises ValidationError."""
        print(correct_topology)
        bad_topology = correct_topology.replace('image: debian', 'image: debn', 1)
        stream = io.StringIO(bad_topology)
        definition = definitions.load_definition(stream)

        with pytest.raises(exceptions.ValidationError):
            definitions.validate_topology_definition(definition)

    @pytest.mark.parametrize(
        'name, raises',
        [
            ('First-is-not-lower-case12', True),
            ('first-is-lower-case12', False),
            ('invalid_character', True),
            ('-cannot-be-first', True),
            ('cAPITAL-LETTERS-ok', False),
            ('okay-name-without-numbers', False),
            ('2-number-cannot-be-first', True),
        ],
    )
    def test_definition_name_validness(self, get_terraform_client, name, raises, correct_topology):  # pylint: disable=unused-argument
        """Test that topology definition names are validated correctly."""
        new_topology = correct_topology.replace('sandbox-definition', name, 1)
        stream = io.StringIO(new_topology)

        if raises:
            with pytest.raises(exceptions.ValidationError):
                definitions.load_definition(stream)
        else:
            definition = definitions.load_definition(stream)
            definitions.validate_topology_definition(definition)

    def test_unique_host_network_router_names(self, get_terraform_client, correct_topology):  # pylint: disable=unused-argument
        """Test that duplicate names across hosts, networks and routers raise ValidationError."""
        new_topology = (
            correct_topology
            .replace('- name: deb', '- name: same-name', 1)
            .replace('- name: router', '- name: same-name', 1)
            .replace('- name: switch', '- name: same-name', 1)
        )
        stream = io.StringIO(new_topology)
        with pytest.raises(exceptions.ValidationError):
            definitions.load_definition(stream)

    def test_unique_host_network_names(self, get_terraform_client, correct_topology):  # pylint: disable=unused-argument
        """Test that duplicate names between hosts and networks raise ValidationError."""
        new_topology = correct_topology.replace('- name: deb', '- name: same-name', 1).replace(
            '- name: router', '- name: same-name', 1
        )
        stream = io.StringIO(new_topology)
        with pytest.raises(exceptions.ValidationError):
            definitions.load_definition(stream)

    @pytest.mark.parametrize('group_name', ['management', 'routers', 'hosts'])
    def test_redefinition_of_default_groups_fails(
        self,
        get_terraform_client,
        group_name,
        correct_topology,  # pylint: disable=unused-argument
    ):
        """Test that redefining reserved group names raises ValidationError."""
        new_topology = correct_topology.replace(
            '- name: linux-machines', '- name: ' + group_name, 1
        )
        stream = io.StringIO(new_topology)
        definition = definitions.load_definition(stream)

        with pytest.raises(exceptions.ValidationError):
            definitions.validate_topology_definition(definition)

    @pytest.mark.parametrize(
        'group_name', ['ssh_nodes', 'winrm_nodes', 'user_accessible_nodes', 'hidden_hosts']
    )
    def test_redefinition_of_default_groups_with_invalid_names_fails(self, mocker, group_name):
        """Some of the default names use underscore, which wouldn't pass
        the load_definition function.
        To test if the redefinition fails, we need to bypass the load_definition function."""

        hosts_group = mocker.Mock()
        hosts_group.name = group_name

        topology_definition = mocker.Mock()
        topology_definition.name = 'name'
        topology_definition.groups = [hosts_group]
        mocker.patch(
            'crczp.sandbox_definition_app.lib.definitions.get_definition',
            return_value=topology_definition,
        )

        with pytest.raises(exceptions.ValidationError):
            definitions.validate_topology_definition(topology_definition)


class TestForwardingReservedAddresses:
    """Tests for the address the OpenStack driver reserves on a mirror-destination network."""

    @pytest.fixture(autouse=True)
    def forwarding_enabled(self, mocker):
        """Enable network forwarding on a copy of the app config, as OpenStack."""
        config = copy.copy(settings.CRCZP_CONFIG)
        config.network_forwarding_enabled = True
        config.openstack = copy.copy(settings.CRCZP_CONFIG.openstack)
        config.openstack.hypervisor_cidr = '10.99.0.0/16'
        mocker.patch.object(settings, 'CRCZP_CONFIG', config)
        mocker.patch.object(settings, 'AWS_PROVIDER_CONFIGURED', False)

    def test_shipped_definition_passes(
        self,
        get_terraform_client,  # pylint: disable=unused-argument
        topology_definition_forwarding,
    ):
        """The example definition leaves the reserved address free."""
        definitions.validate_topology_definition(topology_definition_forwarding)

    @pytest.mark.parametrize('mapping_kind', ['net_mappings', 'router_mappings'])
    def test_reserved_address_rejected(self, topology_definition_forwarding, mapping_kind):
        """A host or a router mapped to the reserved address is rejected, naming the node."""
        (mapping,) = [
            mapping
            for mapping in getattr(topology_definition_forwarding, mapping_kind)
            if mapping.network == 'monitoring-switch'
        ]
        mapping.ip = '10.10.40.3'

        with pytest.raises(exceptions.ValidationError) as exc_info:
            definitions.validate_topology_definition(topology_definition_forwarding)

        assert '10.10.40.3' in str(exc_info.value)
        assert 'monitoring-switch' in str(exc_info.value)

    def test_reserved_address_on_another_network_is_ignored(
        self,
        get_terraform_client,  # pylint: disable=unused-argument
        topology_definition_forwarding,
    ):
        """Only a mirror-destination network reserves the third address."""
        (mapping,) = [
            mapping
            for mapping in topology_definition_forwarding.net_mappings
            if mapping.host == 'server'
        ]
        mapping.ip = '10.10.20.3'

        definitions.validate_topology_definition(topology_definition_forwarding)

    def test_destination_network_too_small(self, topology_definition_forwarding):
        """A destination network with no address to spare is rejected."""
        (network,) = [
            network
            for network in topology_definition_forwarding.networks
            if network.name == 'monitoring-switch'
        ]
        network.cidr = '10.10.40.0/30'

        with pytest.raises(exceptions.ValidationError, match='/29'):
            definitions.validate_topology_definition(topology_definition_forwarding)

    def test_not_applied_on_aws(
        self,
        mocker,
        get_terraform_client,  # pylint: disable=unused-argument
        topology_definition_forwarding,
    ):
        """The reservation is an OpenStack one and must not constrain AWS topologies."""
        mocker.patch.object(settings, 'AWS_PROVIDER_CONFIGURED', True)
        (mapping,) = [
            mapping
            for mapping in topology_definition_forwarding.net_mappings
            if mapping.network == 'monitoring-switch'
        ]
        mapping.ip = '10.10.40.3'

        definitions.validate_topology_definition(topology_definition_forwarding)
