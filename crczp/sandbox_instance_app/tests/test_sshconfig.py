from crczp.sandbox_instance_app.lib import sshconfig
from django.conf import settings


class TestGetSshConfig:
    def test_create_user_config_success(self, top_ins, user_ssh_config):
        proxy_jump = settings.CRCZP_CONFIG.proxy_jump_to_man
        result = sshconfig.CrczpUserSSHConfig(top_ins, proxy_jump.Host, 'stack-name')
        assert result.asdict() == user_ssh_config.asdict()

    def test_create_management_config_success(self, top_ins, management_ssh_config):
        proxy_jump = settings.CRCZP_CONFIG.proxy_jump_to_man
        result = sshconfig.CrczpMgmtSSHConfig(top_ins, proxy_jump.Host, 'pool-prefix')
        assert result.asdict() == management_ssh_config.asdict()

    def test_create_ansible_config_success(self, top_ins, ansible_ssh_config):
        proxy_jump = settings.CRCZP_CONFIG.proxy_jump_to_man
        result = sshconfig.CrczpAnsibleSSHConfig(
            top_ins, '/root/.ssh/pool_mng_key',
            proxy_jump.Host, proxy_jump.User, '/root/.ssh/id_rsa')
        assert result.asdict() == ansible_ssh_config.asdict()
