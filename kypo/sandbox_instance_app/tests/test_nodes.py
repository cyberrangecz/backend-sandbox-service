import pytest

from kypo.sandbox_instance_app.lib import nodes
from kypo.sandbox_common_lib import exceptions


class TestNodeAction:
    @pytest.mark.parametrize("action", [
        "suspend",
        "resume",
        "reboot",
    ])
    def test_node_action_success(self, mocker, action):
        mock_client = mocker.patch("kypo.sandbox_common_lib.utils.get_ostack_client")
        mock_instance = mock_client.return_value
        action_dict = {
            'suspend': mock_instance.suspend_node,
            'resume': mock_instance.resume_node,
            'reboot': mock_instance.reboot_node,
        }

        sb_mock = mocker.MagicMock()
        node_name = "node_name"
        nodes.node_action(sb_mock, node_name, action)

        action_dict[action].assert_called_once_with(
            sb_mock.allocation_unit.get_stack_name.return_value, node_name)

    def test_node_action_unknown_action(self, mocker):
        mocker.patch("kypo.sandbox_common_lib.utils.get_ostack_client")
        with pytest.raises(exceptions.ValidationError):
            nodes.node_action(mocker.MagicMock(), "node_name", "non-action")


class TestGetNode:
    def test_get_node(self, mocker):
        mock_client = mocker.patch(
            "kypo.openstack_driver.ostack_client.KypoOstackClient.get_node")
        result = nodes.get_node(mocker.MagicMock(), "node_name")
        assert result == mock_client.return_value
