import io

import pytest
import yaml

from crczp.sandbox_common_lib import exceptions
from crczp.sandbox_definition_app.lib import definitions

pytestmark = pytest.mark.django_db


class TestFlavorMapping:
    @pytest.fixture(autouse=True)
    def setup(self, mocker, flavor_dict):
        mock_client = mocker.MagicMock()
        mock_client.get_flavors_dict.return_value = flavor_dict
        mocker.patch('crczp.sandbox_common_lib.utils.get_terraform_client', return_value=mock_client)
        yield

    def test_no_custom_flavors_successful(self, definition_custom_flavors, get_terraform_client):
        top_def = definitions.load_definition(io.StringIO(definition_custom_flavors))
        definitions.validate_topology_definition(top_def)

    @pytest.mark.parametrize('flavor, alias',
                             [
                                 ("a2.small2x4", "custom.small"),
                                 ("a1.tiny1x2", "standard.tiny")
                             ])
    def test_custom_flavor_alias_successful(self, flavor, alias, definition_custom_flavors, get_terraform_client):
        new_definition = definition_custom_flavors.replace(flavor, alias, 1)
        top_def = definitions.load_definition(io.StringIO(new_definition))
        definitions.validate_topology_definition(top_def)

    def test_unknown_alias_unsuccessful(self, definition_custom_flavors, get_terraform_client):
        new_definition = definition_custom_flavors.replace("standard.small", "unknown_alias", 1)
        top_def = definitions.load_definition(io.StringIO(new_definition))

        with pytest.raises(exceptions.ValidationError):
            definitions.validate_topology_definition(top_def)
