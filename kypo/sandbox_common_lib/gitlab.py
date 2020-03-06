import re
import gitlab
from urllib import parse
import requests
import structlog

from kypo.sandbox_common_lib import exceptions

LOG = structlog.get_logger()


def get_file_from_repo(url: str, rev: str, token: str, path: str) -> str:
    """Get file from repo as a string."""
    try:
        gl = gitlab.Gitlab(get_host_url(url), private_token=token)
        project = gl.projects.get(get_project_path(url))
        file = project.files.get(file_path=path, ref=rev)
        return file.decode()
    except (requests.exceptions.RequestException, gitlab.exceptions.GitlabError) as ex:
        raise exceptions.GitError(ex)


def get_host_url(url: str, prot: str = 'http') -> str:
    """Return git host url."""
    address = url.replace('git@', '', 1).split(':')[0]
    return f'{prot}://{address}'


def get_project_path(url: str) -> str:
    """Return URL encoded path of the project."""
    path = re.sub('.git$', '', url).split(':')[-1]
    quoted_path = parse.quote_plus(path)
    return quoted_path
