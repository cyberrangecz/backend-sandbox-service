"""Tests for the NetBird management API client and its factory helpers."""

# Locally defined fixtures are injected by name and the client's private
# attributes are asserted directly, so these test-only diagnostics are noise.
# pylint: disable=protected-access,redefined-outer-name,unused-argument,too-few-public-methods

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests as http_requests

from crczp.sandbox_common_lib.netbird_client import (
    NetbirdApiError,
    NetbirdClient,
    NetbirdConfigError,
    get_client_management_url,
    get_netbird_client,
)

MANAGEMENT_URL = 'https://nb.example.com/'
BASE = 'https://nb.example.com'
PAT = 'pat-token'


def make_response(
    status_code: int, json_data: dict[str, Any] | None = None, text: str = ''
) -> MagicMock:
    """Build a fake requests.Response with the given status, JSON and text."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.text = text
    return resp


@pytest.fixture
def session(mocker: Any) -> MagicMock:
    """Patch the client's requests.Session and return the fake session."""
    fake_session = MagicMock()
    mocker.patch(
        'crczp.sandbox_common_lib.netbird_client.http_requests.Session',
        return_value=fake_session,
    )
    return fake_session


@pytest.fixture
def client(session: MagicMock) -> NetbirdClient:
    """Return a NetbirdClient wired to the patched session."""
    return NetbirdClient(MANAGEMENT_URL, PAT)


class TestNetbirdApiError:
    """Tests for the NetbirdApiError message formatting."""

    def test_message_includes_method_url_status(self):
        """The error exposes method, url, status and body and embeds them."""
        exc = NetbirdApiError('POST', f'{BASE}/api/groups', 500, 'boom')
        assert exc.method == 'POST'
        assert exc.url == f'{BASE}/api/groups'
        assert exc.status_code == 500
        assert exc.body == 'boom'
        assert 'POST' in str(exc) and '500' in str(exc)

    def test_message_truncates_long_body(self):
        """Only the first 200 chars of the body are embedded in the message."""
        exc = NetbirdApiError('GET', f'{BASE}/api/groups', 500, 'x' * 1000)
        # Only the first 200 chars of the body are embedded in the message.
        assert 'x' * 200 in str(exc)
        assert 'x' * 201 not in str(exc)


class TestNetbirdClientInit:
    """Tests for NetbirdClient construction."""

    def test_strips_trailing_slash_and_sets_auth_header(self, session):
        """The auth header is set from the PAT on construction."""
        NetbirdClient(MANAGEMENT_URL, PAT)
        session.headers.update.assert_called_once()
        headers = session.headers.update.call_args.args[0]
        assert headers['Authorization'] == f'Token {PAT}'

    def test_verify_falls_back_to_true_when_ca_empty(self, mocker, session):
        """An empty CA setting must not disable TLS verification."""
        mocker.patch(
            'crczp.sandbox_common_lib.netbird_client.settings.CRCZP_CONFIG',
            new=SimpleNamespace(ssl_ca_certificate_verify=''),
        )
        NetbirdClient(MANAGEMENT_URL, PAT)
        assert session.verify is True

    def test_verify_uses_ca_path_when_set(self, mocker, session):
        """A configured CA path is passed through to the session verify setting."""
        mocker.patch(
            'crczp.sandbox_common_lib.netbird_client.settings.CRCZP_CONFIG',
            new=SimpleNamespace(ssl_ca_certificate_verify='/etc/ssl/certs'),
        )
        NetbirdClient(MANAGEMENT_URL, PAT)
        assert session.verify == '/etc/ssl/certs'


class TestGroups:
    """Tests for the group endpoints."""

    def test_create_group_returns_id(self, client, session):
        """create_group posts the payload and returns the new group id."""
        session.request.return_value = make_response(200, {'id': 'grp-1'})
        result = client.create_group('my-group')
        assert result == 'grp-1'
        session.request.assert_called_once_with(
            'POST',
            f'{BASE}/api/groups',
            timeout=(5, 30),
            json={'name': 'my-group', 'peers': [], 'resources': []},
        )

    def test_create_group_raises_on_error(self, client, session):
        """A 4xx response raises NetbirdApiError with the status and method."""
        session.request.return_value = make_response(400, text='bad request')
        with pytest.raises(NetbirdApiError) as exc_info:
            client.create_group('my-group')
        assert exc_info.value.status_code == 400
        assert exc_info.value.method == 'POST'

    def test_delete_group_tolerates_404(self, client, session):
        """Deleting an already-gone group does not raise."""
        session.request.return_value = make_response(404)
        client.delete_group('grp-1')  # must not raise

    def test_delete_group_success(self, client, session):
        """A 2xx delete succeeds silently."""
        session.request.return_value = make_response(200)
        client.delete_group('grp-1')

    def test_delete_group_raises_on_error(self, client, session):
        """A 5xx delete raises NetbirdApiError."""
        session.request.return_value = make_response(500, text='err')
        with pytest.raises(NetbirdApiError):
            client.delete_group('grp-1')


class TestSetupKeys:
    """Tests for the setup-key endpoints."""

    def test_create_setup_key_returns_id_and_value(self, client, session):
        """create_setup_key returns (id, key) and posts the expected payload."""
        session.request.return_value = make_response(200, {'id': 'key-1', 'key': 'secret-value'})
        key_id, key_value = client.create_setup_key('name', ['grp-1'], 3600)
        assert (key_id, key_value) == ('key-1', 'secret-value')
        payload = session.request.call_args.kwargs['json']
        assert payload['type'] == 'reusable'
        assert payload['expires_in'] == 3600
        assert payload['auto_groups'] == ['grp-1']
        assert payload['usage_limit'] == 0
        assert payload['ephemeral'] is False

    def test_delete_setup_key_tolerates_404(self, client, session):
        """Deleting an already-gone setup key does not raise."""
        session.request.return_value = make_response(404)
        client.delete_setup_key('key-1')

    def test_delete_setup_key_raises_on_error(self, client, session):
        """A 5xx delete raises NetbirdApiError."""
        session.request.return_value = make_response(500, text='err')
        with pytest.raises(NetbirdApiError):
            client.delete_setup_key('key-1')


class TestRoutes:
    """Tests for the route endpoints."""

    def test_create_route_returns_id(self, client, session):
        """create_route posts the distribution groups and returns the route id."""
        session.request.return_value = make_response(200, {'id': 'route-1'})
        result = client.create_route(
            network_id='net-1',
            cidr='10.0.0.0/24',
            peer_group_ids=['host-grp'],
            client_group_ids=['client-grp'],
            description='desc',
        )
        assert result == 'route-1'
        payload = session.request.call_args.kwargs['json']
        assert payload['network_id'] == 'net-1'
        assert payload['network'] == '10.0.0.0/24'
        assert payload['peer_groups'] == ['host-grp']
        # The required distribution `groups` field carries the client group.
        assert payload['groups'] == ['client-grp']
        # `access_control_groups` must NOT be set: it would switch the route into
        # the resource-ACL model and drop forwarded traffic our policy authorises.
        assert 'access_control_groups' not in payload

    def test_delete_route_tolerates_404(self, client, session):
        """Deleting an already-gone route does not raise."""
        session.request.return_value = make_response(404)
        client.delete_route('route-1')


class TestPolicies:
    """Tests for the policy endpoints."""

    def test_create_policy_returns_id(self, client, session):
        """create_policy posts an accept rule and returns the policy id."""
        session.request.return_value = make_response(200, {'id': 'pol-1'})
        result = client.create_policy('name', ['client-grp'], ['host-grp'])
        assert result == 'pol-1'
        payload = session.request.call_args.kwargs['json']
        assert payload['enabled'] is True
        rule = payload['rules'][0]
        assert rule['action'] == 'accept'
        assert rule['sources'] == ['client-grp']
        assert rule['destinations'] == ['host-grp']

    def test_delete_policy_tolerates_404(self, client, session):
        """Deleting an already-gone policy does not raise."""
        session.request.return_value = make_response(404)
        client.delete_policy('pol-1')


class TestNameservers:
    """Tests for the DNS nameserver-group endpoints."""

    def test_create_primary_returns_id_and_payload(self, client, session):
        """A primary group posts udp/53 nameservers, the access group and no domains."""
        session.request.return_value = make_response(200, {'id': 'ns-1'})
        result = client.create_nameserver_group(
            name='stack-dns',
            servers=['10.0.0.5'],
            distribution_group_ids=['access-grp'],
            primary=True,
            domains=[],
            search_domains_enabled=False,
            description='stack DNS',
        )
        assert result == 'ns-1'
        session.request.assert_called_once_with(
            'POST',
            f'{BASE}/api/dns/nameservers',
            timeout=(5, 30),
            json={
                'name': 'stack-dns',
                'description': 'stack DNS',
                'nameservers': [{'ip': '10.0.0.5', 'ns_type': 'udp', 'port': 53}],
                'enabled': True,
                'groups': ['access-grp'],
                'primary': True,
                'domains': [],
                'search_domains_enabled': False,
            },
        )

    def test_create_domain_scoped_payload(self, client, session):
        """A domain-scoped group lists every server and enables search domains."""
        session.request.return_value = make_response(200, {'id': 'ns-2'})
        client.create_nameserver_group(
            name='stack-dns',
            servers=['10.0.0.5', '10.0.0.6'],
            distribution_group_ids=['access-grp'],
            primary=False,
            domains=['sandbox.local'],
            search_domains_enabled=True,
        )
        payload = session.request.call_args.kwargs['json']
        assert payload['nameservers'] == [
            {'ip': '10.0.0.5', 'ns_type': 'udp', 'port': 53},
            {'ip': '10.0.0.6', 'ns_type': 'udp', 'port': 53},
        ]
        assert payload['primary'] is False
        assert payload['domains'] == ['sandbox.local']
        assert payload['search_domains_enabled'] is True

    def test_create_raises_on_error(self, client, session):
        """A 4xx/5xx response raises NetbirdApiError."""
        session.request.return_value = make_response(500, text='boom')
        with pytest.raises(NetbirdApiError):
            client.create_nameserver_group(
                name='x',
                servers=['1.1.1.1'],
                distribution_group_ids=['g'],
                primary=True,
                domains=[],
                search_domains_enabled=False,
            )

    def test_delete_tolerates_404(self, client, session):
        """Deleting an already-gone nameserver group does not raise."""
        session.request.return_value = make_response(404)
        client.delete_nameserver_group('ns-1')

    def test_delete_raises_on_error(self, client, session):
        """A non-404 error response raises NetbirdApiError."""
        session.request.return_value = make_response(500, text='boom')
        with pytest.raises(NetbirdApiError):
            client.delete_nameserver_group('ns-1')


class TestPeers:
    """Tests for the peer endpoints and group-peer listing."""

    def test_list_group_peer_ids_returns_ids(self, client, session):
        """Peer ids are extracted from the group's peer objects."""
        session.request.return_value = make_response(
            200, {'id': 'grp-1', 'peers': [{'id': 'p1', 'name': 'peer-one'}, {'id': 'p2'}]}
        )
        result = client.list_group_peer_ids('grp-1')
        assert result == ['p1', 'p2']
        session.request.assert_called_once_with('GET', f'{BASE}/api/groups/grp-1', timeout=(5, 30))

    def test_list_group_peer_ids_returns_empty_on_404(self, client, session):
        """A 404 group yields an empty peer list."""
        session.request.return_value = make_response(404)
        result = client.list_group_peer_ids('grp-1')
        assert result == []

    def test_list_group_peer_ids_returns_empty_when_peers_missing(self, client, session):
        """A group without a peers key yields an empty list."""
        session.request.return_value = make_response(200, {'id': 'grp-1'})
        assert client.list_group_peer_ids('grp-1') == []

    def test_list_group_peer_ids_returns_empty_when_peers_none(self, client, session):
        """A null peers value yields an empty list."""
        session.request.return_value = make_response(200, {'id': 'grp-1', 'peers': None})
        assert client.list_group_peer_ids('grp-1') == []

    def test_list_group_peer_ids_returns_empty_when_peers_empty(self, client, session):
        """An empty peers list yields an empty list."""
        session.request.return_value = make_response(200, {'id': 'grp-1', 'peers': []})
        assert client.list_group_peer_ids('grp-1') == []

    def test_list_group_peer_ids_raises_on_500(self, client, session):
        """A 5xx response raises NetbirdApiError."""
        session.request.return_value = make_response(500, text='err')
        with pytest.raises(NetbirdApiError) as exc_info:
            client.list_group_peer_ids('grp-1')
        assert exc_info.value.status_code == 500
        assert exc_info.value.method == 'GET'

    def test_delete_peer_tolerates_404(self, client, session):
        """Deleting an already-gone peer does not raise."""
        session.request.return_value = make_response(404)
        client.delete_peer('peer-1')  # must not raise

    def test_delete_peer_success(self, client, session):
        """A 2xx delete issues the expected DELETE request."""
        session.request.return_value = make_response(200)
        client.delete_peer('peer-1')
        session.request.assert_called_once_with(
            'DELETE', f'{BASE}/api/peers/peer-1', timeout=(5, 30)
        )

    def test_delete_peer_raises_on_500(self, client, session):
        """A 5xx delete raises NetbirdApiError."""
        session.request.return_value = make_response(500, text='err')
        with pytest.raises(NetbirdApiError):
            client.delete_peer('peer-1')


class TestRequestExceptionHandling:
    """Tests for transport-level error wrapping."""

    def test_connection_error_wrapped_as_api_error(self, client, session):
        """A transport failure is wrapped as a status-0 NetbirdApiError."""
        session.request.side_effect = http_requests.ConnectionError('refused')
        with pytest.raises(NetbirdApiError) as exc_info:
            client.create_group('my-group')
        # A transport-level failure surfaces as status_code 0 rather than
        # leaking the raw requests exception out of the client.
        assert exc_info.value.status_code == 0
        assert 'refused' in exc_info.value.body


def patch_netbird_config(mocker: Any, netbird_cfg: Any) -> None:
    """Swap CRCZP_CONFIG for a namespace carrying the given netbird config."""
    # CRCZP_CONFIG is a yamlize Object whose attribute descriptor cannot be
    # safely patched in place, so swap the whole config object for the test.
    mocker.patch(
        'crczp.sandbox_common_lib.netbird_client.settings.CRCZP_CONFIG',
        new=SimpleNamespace(netbird=netbird_cfg, ssl_ca_certificate_verify=True),
    )


class TestFactoryHelpers:
    """Tests for get_netbird_client and get_client_management_url."""

    def test_get_netbird_client_returns_none_when_unconfigured(self, mocker):
        """No netbird config yields no client."""
        patch_netbird_config(mocker, None)
        assert get_netbird_client() is None

    def test_get_netbird_client_builds_client_when_configured(self, mocker, tmp_path):
        """A configured netbird builds a NetbirdClient with the right base url."""
        pat_file = tmp_path / 'pat'
        pat_file.write_text(PAT)
        cfg = SimpleNamespace(
            management_url=MANAGEMENT_URL,
            service_user_pat_file=str(pat_file),
            client_management_url=None,
        )
        patch_netbird_config(mocker, cfg)
        client = get_netbird_client()
        assert isinstance(client, NetbirdClient)
        assert client._base_url == BASE

    def test_get_netbird_client_reads_pat_fresh_each_call(self, mocker, tmp_path):
        """A rotated PAT file is picked up without restarting the service."""
        pat_file = tmp_path / 'pat'
        pat_file.write_text(PAT)
        cfg = SimpleNamespace(
            management_url=MANAGEMENT_URL,
            service_user_pat_file=str(pat_file),
            client_management_url=None,
        )
        patch_netbird_config(mocker, cfg)

        first = get_netbird_client()
        assert first is not None
        assert first._session.headers['Authorization'] == f'Token {PAT}'

        pat_file.write_text('rotated-pat')
        second = get_netbird_client()
        assert second is not None
        assert second._session.headers['Authorization'] == 'Token rotated-pat'

    def test_get_netbird_client_raises_on_empty_pat_file(self, mocker, tmp_path):
        """An empty PAT file raises NetbirdConfigError."""
        pat_file = tmp_path / 'pat'
        pat_file.write_text('   \n')
        cfg = SimpleNamespace(
            management_url=MANAGEMENT_URL,
            service_user_pat_file=str(pat_file),
            client_management_url=None,
        )
        patch_netbird_config(mocker, cfg)
        with pytest.raises(NetbirdConfigError):
            get_netbird_client()

    def test_get_netbird_client_raises_on_missing_pat_file(self, mocker, tmp_path):
        """A missing PAT file is normalised to NetbirdConfigError (not OSError)."""
        cfg = SimpleNamespace(
            management_url=MANAGEMENT_URL,
            service_user_pat_file=str(tmp_path / 'does-not-exist'),
            client_management_url=None,
        )
        patch_netbird_config(mocker, cfg)
        with pytest.raises(NetbirdConfigError):
            get_netbird_client()

    def test_get_netbird_client_raises_on_non_utf8_pat_file(self, mocker, tmp_path):
        """A non-UTF-8 PAT file is normalised to NetbirdConfigError (not ValueError)."""
        pat_file = tmp_path / 'pat'
        pat_file.write_bytes(b'\xff\xfe\x00bad')
        cfg = SimpleNamespace(
            management_url=MANAGEMENT_URL,
            service_user_pat_file=str(pat_file),
            client_management_url=None,
        )
        patch_netbird_config(mocker, cfg)
        with pytest.raises(NetbirdConfigError):
            get_netbird_client()

    def test_get_client_management_url_empty_when_unconfigured(self, mocker):
        """No netbird config yields an empty client URL."""
        patch_netbird_config(mocker, None)
        assert get_client_management_url() == ''

    def test_get_client_management_url_prefers_client_url(self, mocker):
        """The client URL is preferred over the management URL when set."""
        cfg = SimpleNamespace(
            management_url=MANAGEMENT_URL,
            service_user_pat_file='/unused',
            client_management_url='https://client.example.com',
        )
        patch_netbird_config(mocker, cfg)
        assert get_client_management_url() == 'https://client.example.com'

    def test_get_client_management_url_falls_back_to_management_url(self, mocker):
        """The management URL is used when no client URL is set."""
        cfg = SimpleNamespace(
            management_url=MANAGEMENT_URL,
            service_user_pat_file='/unused',
            client_management_url=None,
        )
        patch_netbird_config(mocker, cfg)
        assert get_client_management_url() == MANAGEMENT_URL
