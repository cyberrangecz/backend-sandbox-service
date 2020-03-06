from kypo.sandbox_common_lib import gitlab

URL = 'git@gitlab.ics.muni.cz:kypo-crp/backend-python/kypo-sandbox-service.git'


def test_get_host_url():
    assert gitlab.get_host_url(URL) == 'http://gitlab.ics.muni.cz'
    assert gitlab.get_host_url('git@git.git.com:git@git/git') == 'http://git.git.com'


def test_get_project_path():
    assert gitlab.get_project_path(URL) == 'kypo-crp%2Fbackend-python%2Fkypo-sandbox-service'
    assert gitlab.get_project_path('example.com:kypo/git/.git/repo.git') == 'kypo%2Fgit%2F.git%2Frepo'
