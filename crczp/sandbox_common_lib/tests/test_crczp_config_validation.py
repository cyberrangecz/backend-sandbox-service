"""Tests for CrczpConfiguration attribute validators."""

import pytest

from crczp.sandbox_common_lib import crczp_config_validation


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
        assert crczp_config_validation.validate_netbird_key_expiry(
            object(), key_expiry_seconds
        )

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
