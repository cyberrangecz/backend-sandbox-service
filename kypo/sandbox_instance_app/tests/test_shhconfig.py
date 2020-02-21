from kypo.sandbox_common_lib.config import KypoConfigurationManager as KCM
from kypo.sandbox_instance_app.lib import sshconfig


class TestGetSshConfig:
    def test_create_user_config_success(self, stack, user_ssh_config):
        result = sshconfig.KypoSSHConfig.create_user_config(stack, KCM.config())
        assert str(result) == user_ssh_config

    def test_create_management_config_success(self, stack, management_ssh_config):
        result = sshconfig.KypoSSHConfig.create_management_config(stack, KCM.config())
        assert str(result) == management_ssh_config

    def test_create_ansible_config_success(self, stack, ansible_ssh_config):
        result = sshconfig.KypoSSHConfig.create_ansible_config(stack, KCM.config(),
                                                               mng_key='/root/.ssh/pool_mng_key',
                                                               git_key='/root/.ssh/git_rsa_key',
                                                               proxy_key='/root/.ssh/id_rsa')
        assert str(result) == ansible_ssh_config
