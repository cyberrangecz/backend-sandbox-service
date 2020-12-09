import re
from abc import ABC, abstractmethod
from urllib import parse

import git
import gitlab
import giturlparse
import requests
import structlog
from giturlparse import GitUrlParsed

from kypo.sandbox_common_lib import exceptions
from kypo.sandbox_common_lib.kypo_config import KypoConfiguration

LOG = structlog.get_logger()


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
    def has_key_access(url: str, config: KypoConfiguration) -> bool:
        """Test whether the repo is accessible using SSH key."""
        git_ssh_cmd = 'ssh -o StrictHostKeyChecking=no -i {0}'.format(config.git_private_key)
        try:
            git.cmd.Git().ls_remote(url, env={'GIT_SSH_COMMAND': git_ssh_cmd})
            return True
        except git.exc.GitCommandError:
            return False

    @staticmethod
    def validate(url: str, config: KypoConfiguration) -> GitUrlParsed:
        p: GitUrlParsed = giturlparse.parse(url)
        # TODO support ssh://... in future. Maybe use a better Git URL parser.
        if not p.valid:
            raise exceptions.GitError(f"Could not parse GIT URL: url={url}")
        host = p.host
        port = p.data['port']
        protocol = p.data['protocol']
        user = p.data['_user']

        if host != config.git_server:
            raise exceptions.GitError(
                f"The GIT host does not match the configured value for this instance: expected={config.git_server}, actual={host}")
        if port != '':
            raise exceptions.GitError(
                f"The GIT port does not match the configured value for this instance: expected=22, actual={port}")
        if protocol != 'ssh':
            raise exceptions.GitError(
                f"The GIT protocol does not match the configured value for this instance: expected='ssh', actual={protocol}")
        if user != config.git_user:
            raise exceptions.GitError(
                f"The GIT user does not match the configured value for this instance: expected='ssh', actual={user}")

        return p


class GitlabProvider(DefinitionProvider):
    """Definition provider for Gitlab API."""

    def __init__(self, url: str, config: KypoConfiguration):
        p: GitUrlParsed = self.validate(url, config)
        self.project_path = self.get_project_path(p)
        self.gl = gitlab.Gitlab(config.git_rest_server, private_token=config.git_access_token)

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
    def get_project_path(p: GitUrlParsed) -> str:
        repo_path = f"{p.data['owner']}/{p.data['groups_path']}/{p.data['repo']}"
        return parse.quote_plus(repo_path)


class InternalGitProvider(DefinitionProvider):
    """Definition provider for GitHub-like API."""

    def __init__(self, url: str, config: KypoConfiguration):
        p: GitUrlParsed = self.validate(url, config)
        self.rest_url = self.get_rest_url(config.git_rest_server, p)

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
    def get_rest_url(git_rest_server: str, p: GitUrlParsed) -> str:
        """Return URL of the repository."""
        owner = p.data['owner']
        components: list = p.groups
        components.append(p.data['repo'])
        path = f'{owner}/{";".join(components)}.git'
        return parse.urljoin(git_rest_server, path)

    @staticmethod
    def get_request(url: str):
        """Ger response data as JSON from given URL."""
        response = requests.get(url)
        response.raise_for_status()
        return response
