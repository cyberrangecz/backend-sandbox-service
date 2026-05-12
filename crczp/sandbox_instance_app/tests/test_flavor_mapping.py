"""Tests for custom flavor mapping and validation."""

import io

import pytest

from crczp.sandbox_common_lib import exceptions
from crczp.sandbox_definition_app.lib import definitions

pytestmark = pytest.mark.django_db


class TestFlavorMapping:
    """Tests for topology definition flavor mapping validation."""

    @pytest.fixture(autouse=True)
    def setup(self, mocker, flavor_dict):
        """Set up a mocked Terraform client with a fixed flavor dict."""
        mock_client = mocker.MagicMock()
        mock_client.get_flavors_dict.return_value = flavor_dict
        mocker.patch(
            'crczp.sandbox_common_lib.utils.get_terraform_client', return_value=mock_client
        )
        yield

    def test_no_custom_flavors_successful(  # pylint: disable=unused-argument
        self, definition_custom_flavors, get_terraform_client
    ):
        """Test that a definition with standard flavors validates without error."""
        top_def = definitions.load_definition(io.StringIO(definition_custom_flavors))
        definitions.validate_topology_definition(top_def)

    @pytest.mark.parametrize(
        'flavor, alias', [('a2.small2x4', 'custom.small'), ('a1.tiny1x2', 'standard.tiny')]
    )
    def test_custom_flavor_alias_successful(  # pylint: disable=unused-argument
        self, flavor, alias, definition_custom_flavors, get_terraform_client
    ):
        """Test that a known custom flavor alias resolves without validation error."""
        new_definition = definition_custom_flavors.replace(flavor, alias, 1)
        top_def = definitions.load_definition(io.StringIO(new_definition))
        definitions.validate_topology_definition(top_def)

    def test_unknown_alias_unsuccessful(  # pylint: disable=unused-argument
        self, definition_custom_flavors, get_terraform_client
    ):
        """Test that an unknown flavor alias raises ValidationError."""
        new_definition = definition_custom_flavors.replace('standard.small', 'unknown_alias', 1)
        top_def = definitions.load_definition(io.StringIO(new_definition))

        with pytest.raises(exceptions.ValidationError):
            definitions.validate_topology_definition(top_def)
