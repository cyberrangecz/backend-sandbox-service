from kypo.sandbox_instance_app.lib import sshconfig
from django.conf import settings


class TestGetSshConfig:
    def test_create_user_config_success(self, top_ins, user_ssh_config):
        result = sshconfig.KypoSSHConfig.create_user_config(top_ins, settings.KYPO_CONFIG)
        assert result.serialize() == user_ssh_config

    def test_create_management_config_success(self, top_ins, management_ssh_config):
        result = sshconfig.KypoSSHConfig.create_management_config(top_ins, settings.KYPO_CONFIG)
        assert result.serialize() == management_ssh_config

    def test_create_ansible_config_success(self, top_ins, ansible_ssh_config):
        result = sshconfig.KypoSSHConfig.create_ansible_config(top_ins, settings.KYPO_CONFIG,
                                                               mng_key='/root/.ssh/pool_mng_key',
                                                               git_key='/root/.ssh/git_rsa_key',
                                                               proxy_key='/root/.ssh/id_rsa')
        assert result.serialize() == ansible_ssh_config
