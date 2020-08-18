from kypo.sandbox_common_lib import utils


def get_quota_set():
    """
    Get QuotaSet object.
    """
    client = utils.get_ostack_client()
    return client.get_quota_set()


def get_project_name():
    """
    Get current project name
    """
    client = utils.get_ostack_client()
    return client.get_project_name()
