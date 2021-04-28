import pytest

from kypo.sandbox_common_lib.exceptions import GitError
from kypo.sandbox_common_lib.kypo_config import KypoConfiguration
from kypo.sandbox_definition_app.lib.definition_providers import GitlabProvider, InternalGitProvider


class TestGitlabProvider:
    URL1 = 'git@gitlab.com:kypo-crp/backend-python/kypo-sandbox-service.git'
    URL2 = 'git@gitlab.com:kypo-crp/backend-python/sub-group/GRPX/kypo-sandbox-service.git'
    URL3 = 'git@gitlab.com:123456/kypo-sandbox-service.git'
    CFG = KypoConfiguration(git_server='gitlab.com', git_rest_server='http://gitlab.com:8081')

    @staticmethod
    def get_expected_url(url):
        return url[url.find(':') + 1:-4]

    @pytest.mark.parametrize('url', [URL1, URL2, URL3])
    def test_get_project_path(self, url):
        provider1 = GitlabProvider(url, self.CFG)

        assert provider1.project_path == self.get_expected_url(url)


class TestInternalGitProvider:
    URL_valid_1 = 'git@localhost.lan:/repos/nested-folder/myrepo.git'
    URL_valid_2 = 'ssh://git@localhost.lan/repos/myrepo.git'
    URL_invalid = 'git@localhost.lan:repositories/nested-folder/next-folder/myrepo.git'

    CFG = KypoConfiguration(git_server='localhost.lan', git_rest_server='http://localhost.lan:8081')

    def test_get_repo_url(self):
        provider1 = InternalGitProvider(self.URL_valid_1, self.CFG)
        assert provider1.rest_url == 'http://localhost.lan:8081/repos/nested-folder;myrepo.git'

        provider2 = InternalGitProvider(self.URL_valid_2, self.CFG)
        assert provider2.rest_url == 'http://localhost.lan:8081/repos/myrepo.git'

    def test_invalid_path(self):
        with pytest.raises(GitError):
            InternalGitProvider(self.URL_invalid, self.CFG)


@pytest.mark.integration
class TestGitIntegration:

    def test_def_provider(self):
        assert True
