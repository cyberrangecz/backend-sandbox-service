from abc import ABC, abstractmethod

import gitlab
import requests
import structlog
import giturlparse
import base64

from github.ContentFile import ContentFile
from github import Github, Auth, UnknownObjectException, GithubException

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
        pass

    @abstractmethod
    def get_refs(self):
        """Get a list of refs (branches + tags)."""
        pass

    @abstractmethod
    def get_rev_sha(self, rev: str) -> str:
        """Get a sha of a rev."""
        pass

    @staticmethod
    def validate_https(url: str) -> giturlparse.parser.Parsed:
        try:
            url_parsed = giturlparse.parse(url)
        except giturlparse.parser.ParserError:
            raise exceptions.GitError(f"Could not parse GIT URL: url={url}")

        if not url.startswith("https://") or not url.endswith(".git"):
            raise exceptions.GitError(
                f"Invalid URL. Has to be a GIT URL cloned with HTTPS: expected="
                f"https://example.gitlab.com/[url path].git, actual={url}")

        return url_parsed


class GitlabProvider(DefinitionProvider):
    """Definition provider for Gitlab API."""

    def __init__(self, url: str, config: CrczpConfiguration):
        super().__init__(url, config)
        url_parsed = self.validate_https(url)
        self.project_path = self.get_project_path(url_parsed)

        if self.git_access_token:
            self.gl = gitlab.Gitlab(self.git_rest_server, private_token=self.git_access_token)
        else:
            self.gl = gitlab.Gitlab(self.git_rest_server)

    def get_file(self, path: str, rev: str) -> str:
        """Get file from repo as a string."""
        try:
            project = self.gl.projects.get(self.project_path)
            file = project.files.get(file_path=path, ref=rev)
            return file.decode().decode()  # One decode to get content, one from bytes to str
        except (requests.exceptions.RequestException, gitlab.exceptions.GitlabError) as ex:
            raise exceptions.GitError(ex)

    def get_branches(self):
        try:
            project = self.gl.projects.get(self.project_path)

            return project.branches.list()
        except (requests.exceptions.RequestException, gitlab.exceptions.GitlabError) as ex:
            raise exceptions.GitError(ex)

    def get_tags(self):
        try:
            project = self.gl.projects.get(self.project_path)
            return project.tags.list()
        except (requests.exceptions.RequestException, gitlab.exceptions.GitlabError) as ex:
            raise exceptions.GitError(ex)

    def get_refs(self):
        return self.get_branches() + self.get_tags()

    def get_rev_sha(self, rev: str) -> str:
        try:
            for ref in self.get_refs():
                if ref.name == rev:
                    return ref.commit['id']
            project = self.gl.projects.get(self.project_path)
            commit = project.commits.get(rev)
            return commit.id
        except (requests.exceptions.RequestException, gitlab.exceptions.GitlabError) as ex:
            raise exceptions.GitError('Failed to get sha of the GIT rev.', ex)

    @staticmethod
    def get_project_path(url_parsed) -> str:
        project_path = url_parsed.pathname[:-4] if url_parsed.pathname[-4:] == '.git'\
            else url_parsed.pathname
        # https leaves two // at the start
        path = project_path[2:] if project_path[0:2] == '//' else project_path
        path_start = path.index('/') + 1
        return path[path_start:]


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
            raise exceptions.GitError(f"Cannot find the GitHub repository [url: {url}]") from exc

    def _get_repo_name(self, url: str) -> str:
        return url.removeprefix(self.git_rest_server).removesuffix(".git")

    def get_file(self, path: str, rev: str) -> str:
        """
        Get the plain text content of the file.
        """
        try:
            contents: ContentFile = self.repo.get_contents(path, ref=rev)
        except (UnknownObjectException, GithubException) as exc:
            raise exceptions.GitError(f"Cannot find '{path}' in {self.repo.name} [rev: '{rev}']") from exc

        return base64.b64decode(contents.content).decode()

    def get_refs(self):
        """
        Not implemented as it is not needed.
        """
        return super().get_refs()

    def get_rev_sha(self, rev: str) -> str:
        """
        Return revision specified on the input. This method is created
        only for the compatibility reasons with GitLab client.
        """
        return rev
