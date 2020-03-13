from kypo.sandbox_definition_app.lib.definition_providers import GitlabProvider


class TestGitlabProvider:
    URL = 'git@gitlab.ics.muni.cz:kypo-crp/backend-python/kypo-sandbox-service.git'

    def test_get_host_url(self):
        assert GitlabProvider.get_host_url(self.URL) == 'http://gitlab.ics.muni.cz'
        assert GitlabProvider.get_host_url('git@git.git.com:git@git/git') == 'http://git.git.com'

    def test_get_project_path(self):
        assert GitlabProvider.get_project_path(self.URL) == 'kypo-crp%2Fbackend-python%2Fkypo-sandbox-service'
        assert GitlabProvider.get_project_path('example.com:kypo/git/.git/repo.git') == 'kypo%2Fgit%2F.git%2Frepo'
