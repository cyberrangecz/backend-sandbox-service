import pytest
import requests

from gitlab import GitlabError

from kypo.sandbox_common_lib.exceptions import GitError
from kypo.sandbox_common_lib.kypo_config import KypoConfiguration
from kypo.sandbox_definition_app.lib.definition_providers import GitlabProvider


EXPECTED_RESULT_ARRAY = ['t', 'e', 's', 't']
EXPECTED_RESULT_STR = "test"


class TestGitlabProvider:
    URL1 = 'https://gitlab.com/kypo-crp/backend-python/kypo-sandbox-service.git'
    URL2 = 'https://gitlab.com/kypo-crp/backend-python/sub-group/GRPX/kypo-sandbox-service.git'
    URL3 = 'https://gitlab.com:123456/kypo-sandbox-service.git'
    CFG = KypoConfiguration()

    @staticmethod
    def get_expected_url(url):
        no_prefix = url.replace('https://', '')
        return no_prefix[no_prefix.find('/') + 1:-4]

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


@pytest.mark.integration
class TestGitIntegration:
    def test_def_provider(self):
        assert True
