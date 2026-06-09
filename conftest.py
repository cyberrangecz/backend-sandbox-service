"""Root test fixtures shared across all test directories."""

import fakeredis
import pytest
from rq import Queue as RQQueue


@pytest.fixture(autouse=True)
def fake_redis_for_integration(request, monkeypatch):
    """Replace Redis connections with fakeredis for integration tests.

    This prevents integration tests from requiring a real Redis server.
    All queues share a single FakeServer so job dependencies work correctly.
    """
    if not request.node.get_closest_marker('integration'):
        return

    server = fakeredis.FakeServer()
    fake_conn = fakeredis.FakeRedis(server=server)

    class SharedFakeRedis(fakeredis.FakeRedis):
        """FakeRedis that always uses a shared server instance."""

        def __init__(self, *args, **kwargs):
            # Remove real-connection kwargs irrelevant to fakeredis
            for key in (
                'host',
                'port',
                'ssl',
                'ssl_cert_reqs',
                'username',
                'password',
                'socket_timeout',
                'socket_connect_timeout',
            ):
                kwargs.pop(key, None)
            super().__init__(server=server, **kwargs)

    monkeypatch.setattr('redis.Redis', SharedFakeRedis)
    monkeypatch.setattr('redis.StrictRedis', SharedFakeRedis)

    from django.conf import settings  # noqa: PLC0415

    from crczp.sandbox_instance_app.lib import request_handlers  # noqa: PLC0415

    queues = {
        'default': RQQueue('default', connection=fake_conn),
        'openstack': RQQueue(
            'openstack',
            connection=fake_conn,
            default_timeout=settings.CRCZP_CONFIG.sandbox_build_timeout,
        ),
        'ansible': RQQueue(
            'ansible',
            connection=fake_conn,
            default_timeout=settings.CRCZP_CONFIG.sandbox_ansible_timeout,
        ),
    }

    def fake_get_queue(name='default', **kwargs):
        return queues.get(name, RQQueue(name, connection=fake_conn))

    # Patch django_rq.get_queue so helpers like empty_queues() and get_worker()
    # in tests also use the shared fake connection instead of real Redis.
    # Must patch both the top-level re-export AND the module-local reference that
    # get_queues() (used internally by get_worker()) calls.
    monkeypatch.setattr('django_rq.get_queue', fake_get_queue)
    monkeypatch.setattr('django_rq.queues.get_queue', fake_get_queue)

    # Also patch RequestHandler class attributes set at import time with real Redis.
    monkeypatch.setattr(request_handlers.RequestHandler, 'queue_default', queues['default'])
    monkeypatch.setattr(request_handlers.RequestHandler, 'queue_stack', queues['openstack'])
    monkeypatch.setattr(request_handlers.RequestHandler, 'queue_ansible', queues['ansible'])
