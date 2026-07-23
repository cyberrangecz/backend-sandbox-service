"""Tests for CRCZP configuration parsing."""

import pytest
from yamlize import YamlizingError

from crczp.sandbox_common_lib.crczp_config import (
    OpenStackConfiguration,
    OpenStackConsoleType,
    TopologyCacheMode,
)


class TestTopologyCacheModeCreate:
    """Tests for TopologyCacheMode.create input parsing."""

    @pytest.mark.parametrize(
        ('value', 'expected'),
        [
            ('AGGRESSIVE', TopologyCacheMode.AGGRESSIVE),
            ('FRESH', TopologyCacheMode.FRESH),
            ('FRESH_IMPORT', TopologyCacheMode.FRESH_IMPORT),
            ('fresh_import', TopologyCacheMode.FRESH_IMPORT),
            ('fresh-import', TopologyCacheMode.FRESH_IMPORT),
        ],
    )
    def test_create_valid(self, value, expected):
        """Test that valid values (case- and dash-insensitive) resolve to the right member."""
        assert TopologyCacheMode.create(value) is expected

    def test_create_invalid_raises_readable_value_error(self):
        """Test that an unknown value raises ValueError naming the value and valid options."""
        with pytest.raises(ValueError) as exc_info:
            TopologyCacheMode.create('BOGUS')
        message = str(exc_info.value)
        assert 'BOGUS' in message
        assert 'AGGRESSIVE' in message
        assert 'FRESH_IMPORT' in message


class TestOpenStackConfiguration:
    """Tests for the nested OpenStack provider config block."""

    def test_parses_nested_block(self):
        """All OpenStack settings, including mirror_type, parse from the nested map."""
        config = OpenStackConfiguration.load(
            'auth_url: http://keystone\n'
            'application_credential_id: cred-id\n'
            'application_credential_secret: cred-secret\n'
            'console_type: novnc\n'
            'hypervisor_cidr: 10.99.0.0/16\n'
            'mirror_type: erspanv1\n'
        )
        assert config.auth_url == 'http://keystone'
        assert config.application_credential_id == 'cred-id'
        assert config.console_type is OpenStackConsoleType.NOVNC
        assert config.hypervisor_cidr == '10.99.0.0/16'
        assert config.mirror_type == 'erspanv1'

    def test_defaults_when_unset(self):
        """Omitted settings fall back to their defaults (console spice-html5, mirror_type gre)."""
        config = OpenStackConfiguration.load('auth_url: http://keystone\n')
        assert config.console_type is OpenStackConsoleType.SPICE_HTML5
        assert config.hypervisor_cidr is None
        assert config.mirror_type == 'gre'

    def test_invalid_mirror_type_rejected(self):
        """An unsupported mirror_type fails at config load (replaces the old topology check)."""
        with pytest.raises(YamlizingError):
            OpenStackConfiguration.load('mirror_type: vxlan\n')

    def test_old_flat_keys_rejected(self):
        """The pre-migration flat keys are no longer accepted under the nested block."""
        with pytest.raises(YamlizingError):
            OpenStackConfiguration.load('os_auth_url: http://keystone\n')
