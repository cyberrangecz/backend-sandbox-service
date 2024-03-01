from typing import Optional

from crczp.sandbox_common_lib.crczp_config import CrczpConfiguration, GitType
from .exceptions import ImproperlyConfigured


def get_rest_server(url) -> str:
    """
    Takes a https url, for example sandbox definition clone url,
    and returns the base of the url, f.e. https://gitlab.com/.
    """
    git_server = url.replace("https://", "")
    slash_index = git_server.index('/')
    return f"https://{git_server[:slash_index]}/"


def get_git_token(rest_server, config: CrczpConfiguration) -> Optional[str]:
    """
    Takes a base git url, tries to find a match in config.
    Returns matching access token or None.
    """
    return config.git_providers.get(rest_server, None)


def get_git_type(rest_server) -> GitType:
    """
    Takes git server url.
    Returns corresponding git type.
    """
    if "gitlab." in rest_server:
        return GitType.GITLAB
    elif "github." in rest_server:
        return GitType.GITHUB
    raise ImproperlyConfigured(f"Trying to use unsupported git type: {rest_server} "
                               f"Supported types: gitlab, github")


def get_git_server(rest_server) -> str:
    """
    Takes https rest url.
    Returns url without the https prefix.
    """
    git_server = rest_server.replace("https://", "")
    return git_server.replace("/", "")
