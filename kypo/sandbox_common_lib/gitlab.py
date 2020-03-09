import re
import gitlab
from urllib import parse
import requests
import structlog

from kypo.sandbox_common_lib import exceptions

LOG = structlog.get_logger()


class Repo:
    def __init__(self, url: str, token: str):
        self.url = url
        self.gl = gitlab.Gitlab(self.get_host_url(url), private_token=token)

    def get_file(self, path: str, rev: str,) -> str:
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
        return self.get_branches() + self.get_refs()

    @staticmethod
    def get_host_url(url: str, prot: str = 'http') -> str:
        """Return git host url."""
        address = url.replace('git@', '', 1).split(':')[0]
        return f'{prot}://{address}'

    @staticmethod
    def get_project_path(url: str) -> str:
        """Return URL encoded path of the project."""
        path = re.sub('.git$', '', url).split(':')[-1]
        quoted_path = parse.quote_plus(path)
        return quoted_path
