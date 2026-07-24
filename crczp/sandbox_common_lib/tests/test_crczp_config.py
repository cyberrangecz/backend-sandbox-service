"""Tests for CRCZP configuration parsing."""

import pytest

from crczp.sandbox_common_lib.crczp_config import TopologyCacheMode


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
