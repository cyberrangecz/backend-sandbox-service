import pytest

from kypo.sandbox_common_lib.exceptions import GitError
from kypo.sandbox_common_lib.kypo_config import KypoConfiguration
from kypo.sandbox_definition_app.lib.definition_providers import GitlabProvider, InternalGitProvider


class TestGitlabProvider:
    URL = 'git@gitlab.com:kypo-crp/backend-python/kypo-sandbox-service.git'
    CFG = KypoConfiguration(git_server='gitlab.com', git_rest_server='http://gitlab.com:8081')

    def test_get_project_path(self):
        provider = GitlabProvider(self.URL, self.CFG)
        assert provider.project_path == 'kypo-crp%2Fbackend-python%2Fkypo-sandbox-service'


class TestInternalGitProvider:
    URL1 = 'git@localhost.lan:/repos/nested-folder/myrepo.git'
    URL2 = 'git@localhost.lan:repositories/nested-folder/next-folder/myrepo.git'
    URL3 = 'ssh://git@localhost.lan/repos/myrepo.git'

    CFG = KypoConfiguration(git_server='localhost.lan', git_rest_server='http://localhost.lan:8081')

    def test_get_repo_url(self):
        provider1 = InternalGitProvider(self.URL1, self.CFG)
        assert provider1.rest_url == 'http://localhost.lan:8081/repos/nested-folder;myrepo.git'

        provider2 = InternalGitProvider(self.URL2, self.CFG)
        assert provider2.rest_url == 'http://localhost.lan:8081/repositories/nested-folder;next-folder;myrepo.git'

    def test_invalid_path(self):
        with pytest.raises(GitError):
            InternalGitProvider(self.URL3, self.CFG)


@pytest.mark.integration
class TestGitIntegration:

    def test_def_provider(self):
        assert True
