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


def list_images():
    """
    Get list of images as generator
    """
    client = utils.get_ostack_client()
    return client.list_images()


def get_project_limits():
    """
    Get Absolute limits of OpenStack project.
    """
    client = utils.get_ostack_client()
    return client.get_project_limits()
