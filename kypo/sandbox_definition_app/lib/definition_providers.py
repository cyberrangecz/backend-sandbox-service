from abc import ABC, abstractmethod
from urllib import parse

import git
import gitlab
import requests
import structlog
import giturlparse

from kypo.sandbox_common_lib import exceptions, git_config
from kypo.sandbox_common_lib.kypo_config import KypoConfiguration

LOG = structlog.get_logger()
KYPO_GIT_PREFIX = 'repos'


class DefinitionProvider(ABC):
    """Abstract base class for definition providers."""

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

        if not (url.startswith("https://")) and not (url.startswith("http://")): # or not url.endswith(".git"):
            raise exceptions.GitError(
                f"Invalid URL. Has to be a GIT URL cloned with HTTPS: expected="
                f"https://example.gitlab.com/[url path].git, actual={url}")

        return url_parsed


class GitlabProvider(DefinitionProvider):
    """Definition provider for Gitlab API."""

    def __init__(self, url: str, config: KypoConfiguration):
        url_parsed = self.validate_https(url)
        self.project_path = self.get_project_path(url_parsed)
        git_rest_server = git_config.get_rest_server(url)
        git_access_token = git_config.get_git_token(git_rest_server, config)

        if git_access_token:
            self.gl = gitlab.Gitlab(git_rest_server, private_token=git_access_token)
        else:
            self.gl = gitlab.Gitlab(git_rest_server)

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


class InternalGitProvider(DefinitionProvider):
    """Definition provider for GitHub-like API."""

    def __init__(self, url: str, config: KypoConfiguration):
        url_parsed = self.validate(url, config)
        self.rest_url = self.get_rest_url(config, url_parsed)

    def validate(self, url: str, config: KypoConfiguration):
        url_parsed = DefinitionProvider.validate_https(url)
        pathname = url_parsed.pathname.split('/')
        actual_prefix = pathname[0] \
            if pathname[0] != '' and pathname[0] != str(config.git_ssh_port) else pathname[1]

        if actual_prefix != KYPO_GIT_PREFIX:
            raise exceptions.GitError(
                f'The GIT path name prefix does not match the configured value: '
                f'expected=/{KYPO_GIT_PREFIX}, actual={actual_prefix}.'
            )

        return url_parsed

    def get_file(self, path: str, rev: str) -> str:
        """Get file from repo as a string."""
        try:
            url = f'{self.rest_url}/raw/{rev}/{path}'
            resp = self.get_request(url)
            return resp.text
        except (ConnectionError, requests.RequestException) as ex:
            raise exceptions.GitError(ex)

    def get_branches(self):
        try:
            url = f'{self.rest_url}/branches/'
            resp = self.get_request(url).json()
            return resp
        except (ConnectionError, requests.RequestException) as ex:
            raise exceptions.GitError(ex)

    def get_tags(self):
        try:
            url = f'{self.rest_url}/tags/'
            resp = self.get_request(url).json()
            return resp
        except (ConnectionError, requests.RequestException) as ex:
            raise exceptions.GitError(ex)

    def get_refs(self):
        return self.get_branches() + self.get_tags()

    def get_rev_sha(self, rev):
        try:
            url = f'{self.rest_url}/commits/{rev}'
            resp = self.get_request(url).json()
            return resp['sha']
        except (ConnectionError, requests.RequestException) as ex:
            raise exceptions.GitError('Failed to get sha of the GIT rev.', ex)

    @staticmethod
    def get_rest_url(config: KypoConfiguration, url_parsed) -> str:
        """Return URL of the repository."""
        pathname = url_parsed.pathname
        pathname = '/' + pathname if pathname[0] != '/' else pathname
        pathname = pathname.split('/')
        if pathname[1] == str(config.git_ssh_port):
            pathname.pop(1)
        pathname = f'/{pathname[1]}/{";".join(pathname[2:])}'
        internal_git_server = "http://git-internal.kypo:5000/"
        return parse.urljoin(internal_git_server, pathname)

    @staticmethod
    def get_request(url: str):
        """Ger response data as JSON from given URL."""
        response = requests.get(url)
        response.raise_for_status()
        return response
