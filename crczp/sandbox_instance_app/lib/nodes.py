"""
VM Service module for VM management.
"""
import django_rq
from django.conf import settings
from django.core.cache import cache

from crczp.terraform_driver import TerraformInstance

from crczp.sandbox_instance_app.models import Sandbox
from crczp.sandbox_common_lib import utils, exceptions

CACHE_CONSOLE_PREFIX = "console-"
CACHE_CONSOLE_TIMEOUT = 7200  # the console URLs can last for about 2-3 hours
CACHE_JOB_WORKER_TIME = 300


def node_action(sandbox: Sandbox, node_name: str, action: str) -> None:
    """Perform action on given node."""
    client = utils.get_terraform_client()
    action_dict = {
        'resume': client.resume_node,
        'reboot': client.reboot_node,
    }
    try:
        return action_dict[action](sandbox.allocation_unit.get_stack_name(), node_name)
    except KeyError:
        raise exceptions.ValidationError("Unknown action: '%s'" % action)


def get_node(sandbox: Sandbox, node_name: str) -> TerraformInstance:
    """Retrieve Instance from OpenStack."""
    client = utils.get_terraform_client()
    return client.get_node(sandbox.allocation_unit.get_stack_name(), node_name)


def get_console_url_job(stack_name, node_name, console_type, console_cache_name,
                        job_cache_id_running):
    client = utils.get_terraform_client()
    console_url = client.get_console_url(stack_name, node_name, console_type)
    cache.set(console_cache_name, console_url, CACHE_CONSOLE_TIMEOUT)
    cache.delete(job_cache_id_running)


def get_console_url(sandbox: Sandbox, node_name: str) -> str:
    """Get console URL for given VM."""
    console_cache_name = CACHE_CONSOLE_PREFIX + str(sandbox.id) + '-' + node_name
    job_cache_id_running = CACHE_CONSOLE_PREFIX + str(sandbox.id) + '-' + node_name + '-running'
    console_url = cache.get(console_cache_name, None)
    if console_url:
        return console_url

    job_running = cache.get(job_cache_id_running, False)
    if not job_running:
        cache.set(job_cache_id_running, True, CACHE_JOB_WORKER_TIME)
        django_rq.enqueue(get_console_url_job, sandbox.allocation_unit.get_stack_name(),
                          node_name, settings.CRCZP_CONFIG.os_console_type.value, console_cache_name,
                          job_cache_id_running)
    return ""

