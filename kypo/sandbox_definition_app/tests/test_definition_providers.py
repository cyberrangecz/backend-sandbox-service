import pytest
import requests

from gitlab import GitlabError

from kypo.sandbox_common_lib.exceptions import GitError
from kypo.sandbox_common_lib.kypo_config import KypoConfiguration
from kypo.sandbox_definition_app.lib.definition_providers import GitlabProvider, InternalGitProvider


EXPECTED_RESULT_ARRAY = ['t', 'e', 's', 't']
EXPECTED_RESULT_STR = "test"


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
        gitlab_provider = GitlabProvider(url, self.CFG)
        assert gitlab_provider.project_path == self.get_expected_url(url)

    @pytest.fixture
    def gitlab_project(self, mocker):
        project = mocker.MagicMock()
        return project

    @pytest.fixture
    def gitlab_provider(self, mocker, gitlab_project):
        gitlab_provider = GitlabProvider(self.URL1, self.CFG)
        gitlab_provider.gl.projects.get = mocker.MagicMock()
        gitlab_provider.gl.projects.get.return_value = gitlab_project
        return gitlab_provider

    def test_get_file(self, mocker, gitlab_provider, gitlab_project):
        file = mocker.MagicMock()
        file.decode.return_value = EXPECTED_RESULT_STR.encode()
        gitlab_project.files.get.return_value = file
        assert gitlab_provider.get_file('path', 'rev') == EXPECTED_RESULT_STR

    def test_get_file_project_not_found(self, gitlab_provider):
        gitlab_provider.gl.projects.get.side_effect \
            = GitlabError('project request error')
        with pytest.raises(GitError):
            gitlab_provider.get_file('path', 'rev')

    def test_get_file_file_not_found(self, gitlab_provider, gitlab_project):
        gitlab_project.files.get.side_effect \
            = requests.exceptions.RequestException('file request error')
        with pytest.raises(GitError):
            gitlab_provider.get_file('path', 'rev')

    def test_get_branches(self, gitlab_provider, gitlab_project):
        gitlab_project.branches.list.return_value = EXPECTED_RESULT_ARRAY
        assert gitlab_provider.get_branches() == EXPECTED_RESULT_ARRAY

    def test_get_branches_project_not_found(self, gitlab_provider):
        gitlab_provider.gl.projects.get.side_effect = GitlabError('project request error')
        with pytest.raises(GitError):
            gitlab_provider.get_branches()

    def test_get_branches_branches_not_found(self, gitlab_provider, gitlab_project):
        gitlab_project.branches.list.side_effect \
            = requests.exceptions.RequestException('branch request mock error')
        with pytest.raises(GitError):
            gitlab_provider.get_branches()

    def test_get_tags(self, gitlab_provider, gitlab_project):
        gitlab_project.tags.list.return_value = EXPECTED_RESULT_ARRAY
        assert gitlab_provider.get_tags() == EXPECTED_RESULT_ARRAY

    def test_get_tags_project_not_found(self, gitlab_provider):
        gitlab_provider.gl.projects.get.side_effect = GitlabError('project request mock error')
        with pytest.raises(GitError):
            gitlab_provider.get_tags()

    def test_get_tags_tags_not_found(self, gitlab_provider, gitlab_project):
        gitlab_project.tags.list.side_effect \
            = requests.exceptions.RequestException('tags request mock error')
        with pytest.raises(GitError):
            gitlab_provider.get_tags()

    def test_get_refs(self, mocker, gitlab_provider):
        gitlab_provider.get_branches = mocker.MagicMock()
        gitlab_provider.get_branches.return_value = EXPECTED_RESULT_ARRAY[:2]
        gitlab_provider.get_tags = mocker.MagicMock()
        gitlab_provider.get_tags.return_value = EXPECTED_RESULT_ARRAY[2:]
        assert gitlab_provider.get_refs() == EXPECTED_RESULT_ARRAY

    def test_get_rev_sha_from_refs(self, mocker, gitlab_provider):
        revision1 = mocker.MagicMock()
        revision1.name = "other"
        revision1.id = "1"

        rev_name = "test"
        expected_rev_sha = "2"
        revision2 = mocker.MagicMock()
        revision2.name = rev_name
        revision2.id = expected_rev_sha
        revision2.commit = {'id': expected_rev_sha}

        gitlab_provider.get_refs = mocker.MagicMock()
        gitlab_provider.get_refs.return_value = [revision1, revision2]
        assert gitlab_provider.get_rev_sha(rev_name) == expected_rev_sha

    def test_get_rev_sha_from_commits(self, mocker, gitlab_provider, gitlab_project):
        expected_id = "1"
        commit = mocker.MagicMock()
        commit.id = expected_id
        gitlab_project.commits.get.return_value = commit

        gitlab_provider.get_refs = mocker.MagicMock()
        gitlab_provider.get_refs.return_value = []
        assert gitlab_provider.get_rev_sha("rev") == expected_id

    def test_get_rev_sha_project_not_found(self, gitlab_provider):
        gitlab_provider.gl.projects.get.side_effect \
            = GitlabError('project request mock error')
        with pytest.raises(GitError):
            gitlab_provider.get_rev_sha("rev")

    def test_get_rev_sha_commit_not_found(self, gitlab_provider, gitlab_project):
        gitlab_project.commits.get.side_effect \
            = requests.exceptions.RequestException('commit request mock error')
        with pytest.raises(GitError):
            gitlab_provider.get_rev_sha("rev")


class TestInternalGitProvider:
    URL_VALID_1 = 'git@localhost.lan:/repos/nested-folder/myrepo.git'
    URL_VALID_1_REST = 'http://localhost.lan:8081/repos/nested-folder;myrepo.git'
    URL_VALID_2 = 'ssh://git@localhost.lan/repos/myrepo.git'
    URL_VALID_2_REST = 'http://localhost.lan:8081/repos/myrepo.git'
    URL_INVALID = 'git@localhost.lan:repositories/nested-folder/next-folder/myrepo.git'
    CFG = KypoConfiguration(git_server='localhost.lan', git_rest_server='http://localhost.lan:8081')

    @pytest.mark.parametrize('valid_url, expected_rest_url', [(URL_VALID_1, URL_VALID_1_REST),
                                                              (URL_VALID_2, URL_VALID_2_REST)])
    def test_get_repo_url(self, valid_url, expected_rest_url):
        provider = InternalGitProvider(valid_url, self.CFG)
        assert provider.rest_url == expected_rest_url

    def test_invalid_path(self):
        with pytest.raises(GitError):
            InternalGitProvider(self.URL_INVALID, self.CFG)

    @pytest.fixture
    def internal_provider(self):
        return InternalGitProvider(self.URL_VALID_1, self.CFG)

    @pytest.fixture
    def internal_provider_request(self, mocker, internal_provider):
        internal_provider.get_request = mocker.MagicMock()
        return internal_provider

    @pytest.mark.parametrize('valid_url', [URL_VALID_1, URL_VALID_2])
    def test_validate(self, internal_provider, valid_url):
        url_parsed = internal_provider.validate(valid_url, self.CFG)
        assert url_parsed.pathname == '/repos' + valid_url.split('/repos')[1]
        assert url_parsed.protocol == 'ssh'
        assert url_parsed.href == valid_url

    @pytest.fixture
    def response_success(self, mocker):
        response_success = mocker.MagicMock()
        response_success.json.return_value = EXPECTED_RESULT_STR
        return response_success

    def test_get_file(self, internal_provider_request, response_success):
        response_success.text = EXPECTED_RESULT_STR
        internal_provider_request.get_request.return_value = response_success
        assert internal_provider_request.get_file('path', 'rev') == EXPECTED_RESULT_STR
        internal_provider_request.get_request.\
            assert_called_with(f'{self.URL_VALID_1_REST}/raw/rev/path')

    def test_get_file_connection_error(self, internal_provider):
        with pytest.raises(GitError):
            internal_provider.get_file('path', 'rev')

    def test_get_file_request_error(self, internal_provider_request):
        internal_provider_request.get_request.side_effect =\
            requests.RequestException("test exception")
        with pytest.raises(GitError):
            internal_provider_request.get_file('path', 'rev')

    def test_get_branches(self, internal_provider_request, response_success):
        internal_provider_request.get_request.return_value = response_success
        assert internal_provider_request.get_branches() == EXPECTED_RESULT_STR
        internal_provider_request.get_request.\
            assert_called_with(f'{self.URL_VALID_1_REST}/branches/')

    def test_get_branches_connection_error(self, internal_provider):
        with pytest.raises(GitError):
            internal_provider.get_branches()

    def test_get_branches_request_error(self, internal_provider_request):
        internal_provider_request.get_request.side_effect =\
            requests.RequestException("test exception")
        with pytest.raises(GitError):
            internal_provider_request.get_branches()

    def test_get_tags(self, internal_provider_request, response_success):
        internal_provider_request.get_request.return_value = response_success
        assert internal_provider_request.get_tags() == EXPECTED_RESULT_STR
        internal_provider_request.get_request.assert_called_with(f'{self.URL_VALID_1_REST}/tags/')

    def test_get_tags_connection_error(self, internal_provider):
        with pytest.raises(GitError):
            internal_provider.get_tags()

    def test_get_tags_request_error(self, internal_provider_request):
        internal_provider_request.get_request.side_effect =\
            requests.RequestException("test exception")
        with pytest.raises(GitError):
            internal_provider_request.get_tags()

    def test_get_refs(self, mocker, internal_provider):
        internal_provider.get_branches = mocker.MagicMock()
        internal_provider.get_branches.return_value = EXPECTED_RESULT_ARRAY[:2]
        internal_provider.get_tags = mocker.MagicMock()
        internal_provider.get_tags.return_value = EXPECTED_RESULT_ARRAY[2:]
        assert internal_provider.get_refs() == EXPECTED_RESULT_ARRAY

    def test_get_rev_sha(self, internal_provider_request, response_success):
        expected_result = {'sha': '1'}
        response_success.json.return_value = expected_result

        internal_provider_request.get_request.return_value = response_success
        assert internal_provider_request.get_rev_sha('rev') == expected_result['sha']
        internal_provider_request.get_request.\
            assert_called_with(f'{self.URL_VALID_1_REST}/commits/rev')

    def test_get_rev_sha_connection_error(self, internal_provider):
        with pytest.raises(GitError):
            internal_provider.get_rev_sha('rev')

    def test_get_request(self, mocker, internal_provider):
        expected_value = requests.Response()
        expected_value.status_code = 202
        requests.get = mocker.MagicMock()
        requests.get.return_value = expected_value
        assert internal_provider.get_request('url') == expected_value
        requests.get.assert_called_with('url')

    def test_get_request_raises_exception(self, mocker, internal_provider):
        expected_value = mocker.MagicMock()
        expected_value.raise_for_status.side_effect = requests.HTTPError("test exception")
        requests.get = mocker.MagicMock()
        requests.get.return_value = expected_value
        with pytest.raises(requests.HTTPError):
            internal_provider.get_request('url')


@pytest.mark.integration
class TestGitIntegration:
    def test_def_provider(self):
        assert True
