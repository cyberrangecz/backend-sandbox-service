"""Thin HTTP client for the NetBird management API and its configuration helpers."""

from typing import Any

import requests as http_requests
from django.conf import settings

# Wire defaults applied to each nameserver entry: a plain DNS-over-UDP resolver
# on the standard DNS port.
_DNS_NS_TYPE = 'udp'
_DNS_NS_PORT = 53

# Routing metric assigned to every sandbox route.
_ROUTE_METRIC = 9999

# The not-found status, tolerated as success by the delete and lookup operations.
_NOT_FOUND: frozenset[int] = frozenset({404})

# Management API collection paths; item operations append the resource id.
_GROUPS_PATH = '/api/groups'
_SETUP_KEYS_PATH = '/api/setup-keys'
_ROUTES_PATH = '/api/routes'
_POLICIES_PATH = '/api/policies'
_NAMESERVERS_PATH = '/api/dns/nameservers'
_PEERS_PATH = '/api/peers'


class NetbirdConfigError(Exception):
    """Raised when the Netbird client cannot be configured (e.g. missing PAT)."""


class NetbirdApiError(Exception):
    """Raised when a Netbird API call fails or the endpoint is unreachable."""

    def __init__(self, method: str, url: str, status_code: int, body: str):
        self.method = method
        self.url = url
        self.status_code = status_code
        self.body = body
        super().__init__(f'Netbird API {method} {url} returned {status_code}: {body[:200]}')


class NetbirdClient:
    """Minimal client wrapping the Netbird management REST API."""

    def __init__(self, management_url: str, pat: str, timeout: tuple[int, int] = (5, 30)):
        self._base_url = management_url.rstrip('/')
        self._timeout = timeout
        self._session = http_requests.Session()
        self._session.headers.update({
            'Authorization': f'Token {pat}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        })
        # A falsy value must never disable TLS verification on PAT-bearing traffic:
        # `requests` treats a falsy `verify` as "off", so fall back to True.
        self._session.verify = settings.CRCZP_CONFIG.ssl_ca_certificate_verify or True

    def _request(
        self,
        method: str,
        path: str,
        *,
        accept_statuses: frozenset[int] = frozenset(),
        **kwargs: Any,
    ) -> http_requests.Response:
        url = f'{self._base_url}{path}'
        try:
            response = self._session.request(method, url, timeout=self._timeout, **kwargs)
        except http_requests.RequestException as exc:
            # Normalise the entire requests exception hierarchy to NetbirdApiError
            # so a misbehaving endpoint cannot kill the worker mid-cleanup.
            raise NetbirdApiError(method, url, 0, str(exc)) from exc
        if response.status_code >= 400 and response.status_code not in accept_statuses:
            raise NetbirdApiError(method, url, response.status_code, response.text)
        return response

    def _create_and_get_id(self, path: str, payload: dict[str, Any]) -> str:
        """POST ``payload`` to ``path`` and return the created resource's ID."""
        response = self._request('POST', path, json=payload)
        return str(response.json()['id'])

    def _delete_if_present(self, path: str) -> None:
        """DELETE ``path``, tolerating a 404 if the resource is already gone."""
        self._request('DELETE', path, accept_statuses=_NOT_FOUND)

    # ---- Groups ----

    def create_group(self, name: str) -> str:
        """Create a group and return its ID."""
        return self._create_and_get_id(
            _GROUPS_PATH, {'name': name, 'peers': [], 'resources': []}
        )

    def delete_group(self, group_id: str) -> None:
        """Delete a group, tolerating a 404 if it is already gone."""
        self._delete_if_present(f'{_GROUPS_PATH}/{group_id}')

    # ---- Setup Keys ----

    def create_setup_key(
        self,
        name: str,
        auto_group_ids: list[str],
        expires_in_seconds: int,
    ) -> tuple[str, str]:
        """Create a reusable setup key and return its (id, key) pair."""
        payload = {
            'name': name,
            'type': 'reusable',
            'expires_in': expires_in_seconds,
            'auto_groups': auto_group_ids,
            'usage_limit': 0,
            'ephemeral': False,
            'allow_extra_dns_labels': False,
        }
        response = self._request('POST', _SETUP_KEYS_PATH, json=payload)
        data = response.json()
        return str(data['id']), str(data['key'])

    def delete_setup_key(self, key_id: str) -> None:
        """Delete a setup key, tolerating a 404 if it is already gone."""
        self._delete_if_present(f'{_SETUP_KEYS_PATH}/{key_id}')

    # ---- Routes ----

    def create_route(
        self,
        network_id: str,
        cidr: str,
        peer_group_ids: list[str],
        client_group_ids: list[str],
        description: str = '',
    ) -> str:
        # pylint: disable=too-many-arguments,too-many-positional-arguments
        """Create a network route and return its ID."""
        return self._create_and_get_id(_ROUTES_PATH, {
            'description': description,
            'network_id': network_id,
            'enabled': True,
            'metric': _ROUTE_METRIC,
            'masquerade': True,
            'keep_route': False,
            'peer_groups': peer_group_ids,
            'network': cidr,
            'groups': client_group_ids,
        })

    def delete_route(self, route_id: str) -> None:
        """Delete a route, tolerating a 404 if it is already gone."""
        self._delete_if_present(f'{_ROUTES_PATH}/{route_id}')

    # ---- Policies ----

    def create_policy(
        self,
        name: str,
        source_group_ids: list[str],
        destination_group_ids: list[str],
    ) -> str:
        """Create an access policy and return its ID."""
        return self._create_and_get_id(_POLICIES_PATH, {
            'name': name,
            'description': '',
            'enabled': True,
            'rules': [
                {
                    'name': 'allow-all',
                    'description': '',
                    'enabled': True,
                    'bidirectional': False,
                    'action': 'accept',
                    'protocol': 'all',
                    'sources': source_group_ids,
                    'destinations': destination_group_ids,
                }
            ],
        })

    def delete_policy(self, policy_id: str) -> None:
        """Delete a policy, tolerating a 404 if it is already gone."""
        self._delete_if_present(f'{_POLICIES_PATH}/{policy_id}')

    # ---- DNS ----

    def create_nameserver_group(
        self,
        name: str,
        servers: list[str],
        distribution_group_ids: list[str],
        primary: bool,
        domains: list[str],
        search_domains_enabled: bool,
        description: str = '',
    ) -> str:
        # pylint: disable=too-many-arguments,too-many-positional-arguments
        """Create a DNS nameserver group and return its ID.

        The group hands ``servers`` to every peer in ``distribution_group_ids``
        (the sandbox access group). When ``primary`` is true the servers resolve
        all queries and ``domains`` must be empty; when false they resolve only
        the listed ``domains``.
        """
        return self._create_and_get_id(_NAMESERVERS_PATH, {
            'name': name,
            'description': description,
            'nameservers': [
                {'ip': ip, 'ns_type': _DNS_NS_TYPE, 'port': _DNS_NS_PORT} for ip in servers
            ],
            'enabled': True,
            'groups': distribution_group_ids,
            'primary': primary,
            'domains': domains,
            'search_domains_enabled': search_domains_enabled,
        })

    def delete_nameserver_group(self, nameserver_group_id: str) -> None:
        """Delete a nameserver group, tolerating a 404 if it is already gone."""
        self._delete_if_present(f'{_NAMESERVERS_PATH}/{nameserver_group_id}')

    # ---- Peers ----

    def list_group_peer_ids(self, group_id: str) -> list[str]:
        """Return the peer IDs that are members of the given group.

        A 404 (group already gone) yields an empty list. Used at teardown to find
        the peers registered into a sandbox group so they can be removed.
        """
        response = self._request('GET', f'{_GROUPS_PATH}/{group_id}', accept_statuses=_NOT_FOUND)
        if response.status_code == 404:
            return []
        # Peers come back as {id, name} objects; tolerate plain-string ids too.
        peers = response.json().get('peers') or []
        return [
            peer['id'] if isinstance(peer, dict) else peer
            for peer in peers
            if (isinstance(peer, dict) and peer.get('id')) or isinstance(peer, str)
        ]

    def delete_peer(self, peer_id: str) -> None:
        """Delete a peer, tolerating a 404 if it is already gone."""
        self._delete_if_present(f'{_PEERS_PATH}/{peer_id}')


def _read_service_user_pat(path: str) -> str:
    # Read fresh each call so a rotated secret is picked up without a restart.
    # UnicodeDecodeError is a ValueError, not an OSError, so it must be caught
    # explicitly alongside OSError.
    try:
        with open(path, encoding='utf-8') as pat_file:
            pat = pat_file.read().strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise NetbirdConfigError(
            f'Cannot read Netbird service user PAT file {path}: {exc}'
        ) from exc
    if not pat:
        raise NetbirdConfigError(f'Netbird service user PAT file is empty: {path}')
    return pat


def get_netbird_client() -> 'NetbirdClient | None':
    """Build a NetbirdClient from settings, or None when Netbird is not configured."""
    cfg = settings.CRCZP_CONFIG.netbird
    if cfg is None:
        return None
    return NetbirdClient(cfg.management_url, _read_service_user_pat(cfg.service_user_pat_file))


def get_client_management_url() -> str:
    """Return the management URL trainee clients should use (falls back to the admin URL)."""
    cfg = settings.CRCZP_CONFIG.netbird
    if cfg is None:
        return ''
    return str(cfg.client_management_url or cfg.management_url)
