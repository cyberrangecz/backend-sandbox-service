"""Tests for CrczpConfiguration attribute validators."""

import pytest

from crczp.sandbox_common_lib import crczp_config_validation


class TestValidateHypervisorCidr:
    """Tests for the hypervisor CIDR check."""

    @pytest.mark.parametrize(
        'hypervisor_cidr',
        [
            '10.99.0.0/16',
            '147.251.0.0/16',
            '192.168.1.5/32',
            '10.0.0.1/8',  # host bits set, accepted as the enclosing network
            None,  # the default: the option is only required by network forwarding
        ],
    )
    def test_accepts_valid_cidrs(self, hypervisor_cidr):
        assert crczp_config_validation.validate_hypervisor_cidr(object(), hypervisor_cidr)

    @pytest.mark.parametrize(
        'hypervisor_cidr',
        ['', 'not-a-cidr', '10.99.0.0/33', '300.1.1.0/24', 'fd00::/8'],
    )
    def test_rejects_invalid_cidrs(self, hypervisor_cidr):
        with pytest.raises(ValueError, match='hypervisor_cidr'):
            crczp_config_validation.validate_hypervisor_cidr(object(), hypervisor_cidr)


class TestValidateMirrorType:
    """Tests for the network-forwarding mirror_type check (replaces the topology-side one)."""

    @pytest.mark.parametrize('mirror_type', ['gre', 'erspanv1'])
    def test_accepts_supported_types(self, mirror_type):
        assert crczp_config_validation.validate_mirror_type(object(), mirror_type)

    @pytest.mark.parametrize('mirror_type', ['vxlan', 'GRE', '', 'erspan'])
    def test_rejects_unsupported_types(self, mirror_type):
        with pytest.raises(ValueError, match='mirror_type'):
            crczp_config_validation.validate_mirror_type(object(), mirror_type)


class TestValidateNetbirdKeyExpiry:
    """Tests for the Netbird setup-key expiry bounds check."""

    @pytest.mark.parametrize(
        'key_expiry_seconds',
        [
            crczp_config_validation.NETBIRD_KEY_EXPIRY_MIN_SECONDS,
            crczp_config_validation.NETBIRD_KEY_EXPIRY_MAX_SECONDS,
            1209600,  # the NetbirdConfiguration default (14 days)
        ],
    )
    def test_accepts_values_within_range(self, key_expiry_seconds):
        assert crczp_config_validation.validate_netbird_key_expiry(object(), key_expiry_seconds)

    @pytest.mark.parametrize(
        'key_expiry_seconds',
        [
            crczp_config_validation.NETBIRD_KEY_EXPIRY_MIN_SECONDS - 1,
            crczp_config_validation.NETBIRD_KEY_EXPIRY_MAX_SECONDS + 1,
            0,
            -1,
        ],
    )
    def test_rejects_values_outside_range(self, key_expiry_seconds):
        with pytest.raises(ValueError, match='key_expiry_seconds'):
            crczp_config_validation.validate_netbird_key_expiry(object(), key_expiry_seconds)
