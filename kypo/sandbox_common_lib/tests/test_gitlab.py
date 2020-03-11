from kypo.sandbox_common_lib.gitlab import Repo

URL = 'git@gitlab.ics.muni.cz:kypo-crp/backend-python/kypo-sandbox-service.git'


class TestRepo:
    def test_get_host_url(self):
        assert Repo.get_host_url(URL) == 'http://gitlab.ics.muni.cz'
        assert Repo.get_host_url('git@git.git.com:git@git/git') == 'http://git.git.com'

    def test_get_project_path(self):
        assert Repo.get_project_path(URL) == 'kypo-crp%2Fbackend-python%2Fkypo-sandbox-service'
        assert Repo.get_project_path('example.com:kypo/git/.git/repo.git') == 'kypo%2Fgit%2F.git%2Frepo'
