"""Git provider implementations for accessing sandbox definition files."""

import base64
from abc import ABC, abstractmethod
from typing import Any, override
from urllib.parse import ParseResult, urlparse

import gitlab
import requests
import structlog
from github import Auth, Github, GithubException, UnknownObjectException
from github.ContentFile import ContentFile

from crczp.sandbox_common_lib import exceptions, git_config
from crczp.sandbox_common_lib.crczp_config import CrczpConfiguration

LOG = structlog.get_logger()
CRCZP_GIT_PREFIX = 'repos'


class DefinitionProvider(ABC):
    """Abstract base class for definition providers."""

    def __init__(self, url: str, config: CrczpConfiguration) -> None:
        super().__init__()
        self.git_rest_server = git_config.get_rest_server(url)
        self.git_access_token = git_config.get_git_token(self.git_rest_server, config)

    @abstractmethod
    def get_file(self, path: str, rev: str) -> str:
        """Get file from repo as a string."""

    @abstractmethod
    def get_refs(self) -> list[Any]:
        """Get a list of refs (branches + tags)."""

    @abstractmethod
    def get_rev_sha(self, rev: str) -> str:
        """Get a sha of a rev."""

    @staticmethod
    def validate_https(url: str) -> ParseResult:
        """Validate and parse an HTTPS git URL."""
        if not url.startswith('https://') or not url.endswith('.git'):
            raise exceptions.GitError(
                f'Invalid URL. Has to be a GIT URL cloned with HTTPS: expected='
                f'https://example.gitlab.com/[url path].git, actual={url}'
            )

        return urlparse(url)


class GitlabProvider(DefinitionProvider):
    """Definition provider for Gitlab API."""

    def __init__(self, url: str, config: CrczpConfiguration):
        super().__init__(url, config)
        url_parsed = self.validate_https(url)
        self.project_path = self.get_project_path(url_parsed)

        if self.git_access_token:
            self.gl = gitlab.Gitlab(
                self.git_rest_server,
                private_token=self.git_access_token,
                ssl_verify=not config.git_skip_ssl_verification,
            )
        else:
            self.gl = gitlab.Gitlab(
                self.git_rest_server, ssl_verify=not config.git_skip_ssl_verification
            )

    @override
    def get_file(self, path: str, rev: str) -> str:
        """Get file from repo as a string."""
        try:
            project = self.gl.projects.get(self.project_path)
            file = project.files.get(file_path=path, ref=rev)
            return file.decode().decode()  # One decode to get content, one from bytes to str
        except (requests.exceptions.RequestException, gitlab.exceptions.GitlabError) as ex:
            raise exceptions.GitError(ex) from ex

    def get_branches(self) -> list[Any]:
        """Return a list of branches for this repository."""
        try:
            project = self.gl.projects.get(self.project_path)
            return project.branches.list()
        except (requests.exceptions.RequestException, gitlab.exceptions.GitlabError) as ex:
            raise exceptions.GitError(ex) from ex

    def get_tags(self) -> list[Any]:
        """Return a list of tags for this repository."""
        try:
            project = self.gl.projects.get(self.project_path)
            return project.tags.list()
        except (requests.exceptions.RequestException, gitlab.exceptions.GitlabError) as ex:
            raise exceptions.GitError(ex) from ex

    @override
    def get_refs(self) -> list[Any]:
        return self.get_branches() + self.get_tags()

    @override
    def get_rev_sha(self, rev: str) -> str:
        try:
            for ref in self.get_refs():
                if ref.name == rev:
                    return ref.commit['id']  # type: ignore[no-any-return]
            project = self.gl.projects.get(self.project_path)
            commit = project.commits.get(rev)
            return commit.id  # type: ignore[no-any-return]
        except (requests.exceptions.RequestException, gitlab.exceptions.GitlabError) as ex:
            raise exceptions.GitError('Failed to get sha of the GIT rev.', ex) from ex

    @staticmethod
    def get_project_path(url_parsed: ParseResult) -> str:
        """Extract the GitLab project path from a parsed HTTPS URL."""
        project_path = url_parsed.path[:-4] if url_parsed.path[-4:] == '.git' else url_parsed.path
        path_start = project_path.index('/') + 1
        return project_path[path_start:]


class GitHubProvider(DefinitionProvider):
    """
    Sandbox definition provider compatible with GitHub.
    """

    def __init__(self, url: str, config: CrczpConfiguration) -> None:
        super().__init__(url, config)
        if self.git_access_token:
            github_client = Github(auth=Auth.Token(self.git_access_token))
        else:
            github_client = Github()

        repo_name = self._get_repo_name(url)
        try:
            self.repo = github_client.get_repo(repo_name)
        except GithubException as exc:
            raise exceptions.GitError(f'Cannot find the GitHub repository [url: {url}]') from exc

    def _get_repo_name(self, url: str) -> str:
        return url.removeprefix(self.git_rest_server).removesuffix('.git')

    @override
    def get_file(self, path: str, rev: str) -> str:
        """
        Get the plain text content of the file.
        """
        try:
            contents: ContentFile = self.repo.get_contents(  # type: ignore[assignment]
                path, ref=rev
            )
        except (UnknownObjectException, GithubException) as exc:
            raise exceptions.GitError(
                f"Cannot find '{path}' in {self.repo.name} [rev: '{rev}']"
            ) from exc

        return base64.b64decode(contents.content).decode()

    @override
    def get_refs(self) -> list[Any]:
        """
        Not implemented as it is not needed.
        """
        raise NotImplementedError('get_refs is not supported for GitHub provider')

    @override
    def get_rev_sha(self, rev: str) -> str:
        """
        Return revision specified on the input. This method is created
        only for the compatibility reasons with GitLab client.
        """
        return rev
