"""Tests for definition provider implementations."""

import pytest
import requests
from github import GithubException, UnknownObjectException
from gitlab import GitlabError

from crczp.sandbox_common_lib.crczp_config import CrczpConfiguration, TopologyCacheMode
from crczp.sandbox_common_lib.exceptions import GitError
from crczp.sandbox_definition_app.lib.definition_providers import GitHubProvider, GitlabProvider

EXPECTED_RESULT_ARRAY = ['t', 'e', 's', 't']
EXPECTED_RESULT_STR = 'test'


class TestGitlabProvider:
    """Tests for the GitlabProvider implementation."""

    URL1 = 'https://gitlab.com/crczp/backend-python/sandbox-service.git'
    URL2 = 'https://gitlab.com/crczp/backend-python/sub-group/GRPX/sandbox-service.git'
    URL3 = 'https://gitlab.com:123456/sandbox-service.git'
    CFG = CrczpConfiguration()

    @staticmethod
    def get_expected_url(url: str) -> str:
        """Return the expected project path derived from the URL."""
        no_prefix = url.replace('https://', '')
        return no_prefix[no_prefix.find('/') + 1 : -4]

    @pytest.mark.parametrize('url', [URL1, URL2, URL3])
    def test_get_project_path(self, url):
        """Test that the project path is correctly extracted from the URL."""
        gitlab_provider = GitlabProvider(url, self.CFG)
        assert gitlab_provider.project_path == self.get_expected_url(url)

    @pytest.fixture
    def gitlab_project(self, mocker):
        """Return a mocked Gitlab project."""
        project = mocker.MagicMock()
        return project

    @pytest.fixture
    def gitlab_provider(self, mocker, gitlab_project):  # pylint: disable=redefined-outer-name
        """Return a GitlabProvider with a mocked Gitlab client."""
        gitlab_provider = GitlabProvider(self.URL1, self.CFG)
        gitlab_provider.gl.projects.get = mocker.MagicMock()
        gitlab_provider.gl.projects.get.return_value = gitlab_project
        return gitlab_provider

    def test_get_file(self, mocker, gitlab_provider, gitlab_project):
        """Test that get_file returns the decoded file content."""
        file = mocker.MagicMock()
        file.decode.return_value = EXPECTED_RESULT_STR.encode()
        gitlab_project.files.get.return_value = file
        assert gitlab_provider.get_file('path', 'rev') == EXPECTED_RESULT_STR

    def test_get_file_project_not_found(self, gitlab_provider):
        """Test that a GitlabError from get_file raises GitError."""
        gitlab_provider.gl.projects.get.side_effect = GitlabError('project request error')
        with pytest.raises(GitError):
            gitlab_provider.get_file('path', 'rev')

    def test_get_file_file_not_found(self, gitlab_provider, gitlab_project):
        """Test that a RequestException from get_file raises GitError."""
        gitlab_project.files.get.side_effect = requests.exceptions.RequestException(
            'file request error'
        )
        with pytest.raises(GitError):
            gitlab_provider.get_file('path', 'rev')

    def test_get_branches(self, gitlab_provider, gitlab_project):
        """Test that get_branches returns the expected branch list."""
        gitlab_project.branches.list.return_value = EXPECTED_RESULT_ARRAY
        assert gitlab_provider.get_branches() == EXPECTED_RESULT_ARRAY

    def test_get_branches_project_not_found(self, gitlab_provider):
        """Test that a GitlabError from get_branches raises GitError."""
        gitlab_provider.gl.projects.get.side_effect = GitlabError('project request error')
        with pytest.raises(GitError):
            gitlab_provider.get_branches()

    def test_get_branches_branches_not_found(self, gitlab_provider, gitlab_project):
        """Test that a RequestException from get_branches raises GitError."""
        gitlab_project.branches.list.side_effect = requests.exceptions.RequestException(
            'branch request mock error'
        )
        with pytest.raises(GitError):
            gitlab_provider.get_branches()

    def test_get_tags(self, gitlab_provider, gitlab_project):
        """Test that get_tags returns the expected tag list."""
        gitlab_project.tags.list.return_value = EXPECTED_RESULT_ARRAY
        assert gitlab_provider.get_tags() == EXPECTED_RESULT_ARRAY

    def test_get_tags_project_not_found(self, gitlab_provider):
        """Test that a GitlabError from get_tags raises GitError."""
        gitlab_provider.gl.projects.get.side_effect = GitlabError('project request mock error')
        with pytest.raises(GitError):
            gitlab_provider.get_tags()

    def test_get_tags_tags_not_found(self, gitlab_provider, gitlab_project):
        """Test that a RequestException from get_tags raises GitError."""
        gitlab_project.tags.list.side_effect = requests.exceptions.RequestException(
            'tags request mock error'
        )
        with pytest.raises(GitError):
            gitlab_provider.get_tags()

    def test_get_refs(self, mocker, gitlab_provider):
        """Test that get_refs returns branches and tags combined."""
        gitlab_provider.get_branches = mocker.MagicMock()
        gitlab_provider.get_branches.return_value = EXPECTED_RESULT_ARRAY[:2]
        gitlab_provider.get_tags = mocker.MagicMock()
        gitlab_provider.get_tags.return_value = EXPECTED_RESULT_ARRAY[2:]
        assert gitlab_provider.get_refs() == EXPECTED_RESULT_ARRAY

    def test_get_rev_sha_from_refs(self, mocker, gitlab_provider):
        """Test that get_rev_sha returns the correct commit SHA from refs."""
        revision1 = mocker.MagicMock()
        revision1.name = 'other'
        revision1.id = '1'

        rev_name = 'test'
        expected_rev_sha = '2'
        revision2 = mocker.MagicMock()
        revision2.name = rev_name
        revision2.id = expected_rev_sha
        revision2.commit = {'id': expected_rev_sha}

        gitlab_provider.get_refs = mocker.MagicMock()
        gitlab_provider.get_refs.return_value = [revision1, revision2]
        assert gitlab_provider.get_rev_sha(rev_name) == expected_rev_sha

    def test_get_rev_sha_from_commits(self, mocker, gitlab_provider, gitlab_project):
        """Test that get_rev_sha falls back to commits when rev not found in refs."""
        expected_id = '1'
        commit = mocker.MagicMock()
        commit.id = expected_id
        gitlab_project.commits.get.return_value = commit

        gitlab_provider.get_refs = mocker.MagicMock()
        gitlab_provider.get_refs.return_value = []
        assert gitlab_provider.get_rev_sha('rev') == expected_id

    def test_get_rev_sha_project_not_found(self, gitlab_provider):
        """Test that a GitlabError from get_rev_sha raises GitError."""
        gitlab_provider.gl.projects.get.side_effect = GitlabError('project request mock error')
        with pytest.raises(GitError):
            gitlab_provider.get_rev_sha('rev')

    def test_get_rev_sha_commit_not_found(self, gitlab_provider, gitlab_project):
        """Test that a RequestException from get_rev_sha raises GitError."""
        gitlab_project.commits.get.side_effect = requests.exceptions.RequestException(
            'commit request mock error'
        )
        with pytest.raises(GitError):
            gitlab_provider.get_rev_sha('rev')


class TestGitHubProvider:
    """Tests for the GitHubProvider implementation."""

    URL = 'https://github.com/crczp/sandbox-service.git'

    @pytest.fixture
    def github_repo(self, mocker):
        """Return a mocked GitHub repository."""
        return mocker.MagicMock()

    @pytest.fixture
    def make_github_provider(self, mocker, github_repo):  # pylint: disable=redefined-outer-name
        """Return a factory building a GitHubProvider in a given topology cache mode."""
        mock_github = mocker.MagicMock()
        mock_github.get_repo.return_value = github_repo
        mocker.patch(
            'crczp.sandbox_definition_app.lib.definition_providers.Github',
            return_value=mock_github,
        )

        def _make(mode: TopologyCacheMode = TopologyCacheMode.AGGRESSIVE) -> GitHubProvider:
            return GitHubProvider(self.URL, CrczpConfiguration(topology_cache_mode=mode))

        return _make

    @pytest.fixture
    def github_provider(self, make_github_provider):  # pylint: disable=redefined-outer-name
        """Return a GitHubProvider in the default (AGGRESSIVE) topology cache mode."""
        return make_github_provider()

    def test_get_refs_returns_branches_and_tags(self, github_provider, github_repo):
        """Test that get_refs returns the combined list of branches and tags."""
        branches = ['branch1', 'branch2']
        tags = ['tag1']
        github_repo.get_branches.return_value = branches
        github_repo.get_tags.return_value = tags
        assert github_provider.get_refs() == branches + tags

    def test_get_refs_raises_git_error_on_github_exception(self, github_provider, github_repo):
        """Test that a GithubException from get_refs raises GitError."""
        github_repo.get_branches.side_effect = GithubException(status=404, data={})
        with pytest.raises(GitError):
            github_provider.get_refs()

    def test_get_refs_raises_git_error_on_request_exception(self, github_provider, github_repo):
        """Test that a network error from get_refs raises GitError."""
        github_repo.get_branches.side_effect = requests.exceptions.ConnectionError()
        with pytest.raises(GitError):
            github_provider.get_refs()

    def test_get_file_raises_git_error_on_request_exception(self, github_provider, github_repo):
        """Test that a network error from get_file raises GitError."""
        github_repo.get_contents.side_effect = requests.exceptions.ConnectionError()
        with pytest.raises(GitError):
            github_provider.get_file('topology.yml', 'main')

    def test_get_rev_sha_fresh_resolves_ref_to_commit_sha(self, make_github_provider, github_repo):
        """Test that FRESH mode resolves a branch/tag name to its commit SHA."""
        provider = make_github_provider(TopologyCacheMode.FRESH)
        expected_sha = 'a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2'
        github_repo.get_commit.return_value.sha = expected_sha
        assert provider.get_rev_sha('main') == expected_sha
        github_repo.get_commit.assert_called_once_with('main')

    def test_get_rev_sha_fresh_idempotent_for_full_sha(self, make_github_provider, github_repo):
        """Test that FRESH mode returns an already-resolved SHA unchanged."""
        provider = make_github_provider(TopologyCacheMode.FRESH)
        full_sha = 'a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2'
        github_repo.get_commit.return_value.sha = full_sha
        assert provider.get_rev_sha(full_sha) == full_sha

    def test_get_rev_sha_fresh_raises_git_error_when_ref_not_found(
        self, make_github_provider, github_repo
    ):
        """Test that an UnknownObjectException in FRESH mode raises GitError."""
        provider = make_github_provider(TopologyCacheMode.FRESH)
        github_repo.get_commit.side_effect = UnknownObjectException(status=404, data={})
        with pytest.raises(GitError):
            provider.get_rev_sha('nonexistent')

    def test_get_rev_sha_fresh_raises_git_error_on_github_exception(
        self, make_github_provider, github_repo
    ):
        """Test that a GithubException in FRESH mode raises GitError."""
        provider = make_github_provider(TopologyCacheMode.FRESH)
        github_repo.get_commit.side_effect = GithubException(status=500, data={})
        with pytest.raises(GitError):
            provider.get_rev_sha('main')

    def test_get_rev_sha_fresh_raises_git_error_on_request_exception(
        self, make_github_provider, github_repo
    ):
        """Test that a network error in FRESH mode raises GitError."""
        provider = make_github_provider(TopologyCacheMode.FRESH)
        github_repo.get_commit.side_effect = requests.exceptions.ConnectionError()
        with pytest.raises(GitError):
            provider.get_rev_sha('main')

    @pytest.mark.parametrize('mode', [TopologyCacheMode.AGGRESSIVE, TopologyCacheMode.FRESH_IMPORT])
    def test_get_rev_sha_branch_keyed_returns_rev_unchanged(
        self, make_github_provider, github_repo, mode
    ):
        """Test that AGGRESSIVE/FRESH_IMPORT return the rev unchanged with no GitHub call."""
        provider = make_github_provider(mode)
        assert provider.get_rev_sha('main') == 'main'
        github_repo.get_commit.assert_not_called()


@pytest.mark.integration
class TestGitIntegration:
    """Integration tests for Git definition providers."""  # pylint: disable=too-few-public-methods

    def test_def_provider(self):
        """Placeholder integration test."""
        assert True
