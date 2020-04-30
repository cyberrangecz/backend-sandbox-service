import multiprocessing
import os
import re
from abc import ABC, abstractmethod
from urllib import parse

import git
import gitlab
import requests
import structlog

from kypo.sandbox_common_lib import exceptions
from kypo.sandbox_common_lib.kypo_config import KypoConfiguration

LOG = structlog.get_logger()

# TODO refactor this, doesn't make sense anymore (Probably get rid of local repos altogether).


class DefinitionProvider(ABC):
    """Abstract base class for definition providers."""
    PROVIDABLE_SCHEMES = []

    @abstractmethod
    def get_file(self, path: str, rev: str) -> str:
        """Get file from repo as a string."""
        pass

    @classmethod
    def is_providable(cls, url: str) -> bool:
        """Return True if the url target can be provided by this provider class."""
        return any(url.startswith(x) for x in cls.PROVIDABLE_SCHEMES)

    @abstractmethod
    def get_refs(self):
        """Get a list of refs (branches + tags)."""
        pass

    @abstractmethod
    def get_rev_sha(self, rev: str) -> str:
        """Get a sha of a rev."""

    @staticmethod
    def has_key_access(url: str, config: KypoConfiguration) -> bool:
        """Test whether the repo is accessible using SSH key."""
        git_ssh_cmd = 'ssh -o StrictHostKeyChecking=no -i {0}' \
            .format(config.git_private_key)
        try:
            git.cmd.Git().ls_remote(url, env={'GIT_SSH_COMMAND': git_ssh_cmd})
            return True
        except git.exc.GitCommandError:
            return False

    @staticmethod
    def is_local_repo(url: str) -> bool:
        return url.startswith('file://')

    @staticmethod
    def get_local_repo_path(url: str) -> str:
        return re.sub('^file://', '', url)


class GitlabProvider(DefinitionProvider):
    """Definition provider for Gitlab API."""

    PROVIDABLE_SCHEMES = ['git@gitlab']
    DEFAULT_REST_PROTOCOL = 'https'

    def __init__(self, url: str, token: str):
        self.url = url
        self.gl = gitlab.Gitlab(self.get_host_url(url), private_token=token)

    def get_file(self, path: str, rev: str) -> str:
        """Get file from repo as a string."""
        try:
            project = self.gl.projects.get(self.get_project_path(self.url))
            file = project.files.get(file_path=path, ref=rev)
            return file.decode().decode()  # One decode to get content, one from bytes to str
        except (requests.exceptions.RequestException, gitlab.exceptions.GitlabError) as ex:
            raise exceptions.GitError(ex)

    def get_branches(self):
        try:
            project = self.gl.projects.get(self.get_project_path(self.url))
            return project.branches.list()
        except (requests.exceptions.RequestException, gitlab.exceptions.GitlabError) as ex:
            raise exceptions.GitError(ex)

    def get_tags(self):
        try:
            project = self.gl.projects.get(self.get_project_path(self.url))
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
            project = self.gl.projects.get(self.get_project_path(self.url))
            commit = project.commits.get(rev)
            return commit.id
        except (requests.exceptions.RequestException, gitlab.exceptions.GitlabError) as ex:
            raise exceptions.GitError('Failed to get sha of the GIT rev.', ex)

    @staticmethod
    def get_host_url(url: str) -> str:
        """Return git host url."""
        address = url.replace('git@', '', 1).split(':')[0]
        protocol = GitlabProvider.DEFAULT_REST_PROTOCOL
        return f'{protocol}://{address}'

    @staticmethod
    def get_project_path(url: str) -> str:
        """Return URL encoded path of the project."""
        path = re.sub('.git$', '', url).split(':')[-1]
        quoted_path = parse.quote_plus(path)
        return quoted_path


class InternalGitProvider(DefinitionProvider):
    """Definition provider for GitHub-like API."""

    PROVIDABLE_SCHEMES = ['ssh://git@git-internal-ssh/']
    INTERNAL_HTTP_URL = 'http://git-internal-rest:5000'

    def __init__(self, url: str):
        self.url = url
        self.rest_url = self.get_rest_url(url, self.INTERNAL_HTTP_URL)

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
    def get_rest_url(url: str, git_http_url: str) -> str:
        """Return URL of the repository."""
        parsed = parse.urlparse(url)
        return parse.urljoin(git_http_url, parsed.path)

    @staticmethod
    def get_request(url: str):
        """Ger response data as JSON from given URL."""
        response = requests.get(url)
        response.raise_for_status()
        return response


class GitProvider(DefinitionProvider):
    """Generic Definition provider. Uses directly GIT commands. Should therefore
    work with any git server, if the repo is accessible using SSH key.
    Can handle even local bare repositories.
    """
    GIT_REPOSITORIES = '/tmp'
    PROVIDABLE_SCHEMES = ['file://', 'ssh://', 'git://', 'git@', 'http://', 'https://']

    lock = multiprocessing.Lock()

    def __init__(self, url: str, key_path: str):
        self.url = url
        self.key_path = key_path

    @classmethod
    def get_git_repo(cls, url: str, rev: str, key_path: str) -> git.Repo:
        """ssh_key
        Clone remote repository or retrieve its local copy and checkout revision.

        :raise: git.exc.GitCommandError if the revision is unknown to Git
        """
        with cls.lock:
            git_ssh_cmd = f'ssh -o StrictHostKeyChecking=no -i {key_path}'
            local_repository = os.path.join(cls.GIT_REPOSITORIES,
                                            url, rev).replace(":", "")

            if os.path.isdir(local_repository):
                repo = git.Repo(local_repository)
            else:
                os.makedirs(local_repository, exist_ok=True)
                repo = git.Repo.clone_from(url, local_repository,
                                           env={'GIT_SSH_COMMAND': git_ssh_cmd})
                repo.git.checkout(rev)
            try:
                # check if revision is branch
                repo.git.show_ref('--verify', 'refs/heads/{0}'.format(rev))
                repo.remote().pull(env={'GIT_SSH_COMMAND': git_ssh_cmd})
            except git.exc.GitCommandError as ex:
                LOG.warning("Git pull failed", exception=str(ex))
                pass

            return repo

    def get_file(self, path: str, rev: str):
        """Get file from repo as a string."""
        try:
            repo = self.get_git_repo(self.url, rev, self.key_path)
            return repo.git.show(f'{rev}:{path}')
        except git.exc.GitCommandError as ex:
            raise exceptions.GitError(ex)

    @classmethod
    def is_providable(cls, url: str) -> bool:
        """Any GIT url is providable using the general provider."""
        return any(url.startswith(x) for x in cls.PROVIDABLE_SCHEMES)

    def get_refs(self):
        repo = self.get_git_repo(self.url, 'master', self.key_path)
        return list(repo.references)

    def get_rev_sha(self, rev: str) -> str:
        repo = self.get_git_repo(self.url, rev, self.key_path)
        commit = repo.commit(rev)
        return commit.hexsha
