from kypo.sandbox_instance_app.lib import sandbox_service


class TestGetSshConfig:
    def test_create_user_config_success(self, mocker, stack, user_ssh_config):
        mock_client = mocker.patch("kypo.sandbox_common_lib.utils.get_ostack_client")
        client = mock_client.return_value
        client.get_sandbox.return_value = stack

        result = sandbox_service.SandboxSSHConfigCreator(mocker.MagicMock()).create_user_config()
        assert str(result) == user_ssh_config

    def test_create_management_config_success(self, mocker, stack, management_ssh_config):
        mock_client = mocker.patch("kypo.sandbox_common_lib.utils.get_ostack_client")
        client = mock_client.return_value
        client.get_sandbox.return_value = stack

        result = sandbox_service.SandboxSSHConfigCreator(mocker.MagicMock()).create_management_config()
        assert str(result) == management_ssh_config
