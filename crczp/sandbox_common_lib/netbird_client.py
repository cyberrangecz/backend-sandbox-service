"""Thin HTTP client for the NetBird management API and its configuration helpers."""

from typing import Any

import requests as http_requests
from django.conf import settings

# DNS nameserver wire defaults for nameserver-group entries. NetBird identifies a
# plain DNS-over-UDP resolver as ns_type "udp" on the standard port 53.
_DNS_NS_TYPE = 'udp'
_DNS_NS_PORT = 53


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
        # An empty/falsy value must not silently disable TLS verification:
        # `requests` treats a falsy `verify` as "do not verify", so fall back to
        # `True` (use the default CA store) rather than turning verification off
        # on traffic carrying the PAT and setup keys.
        self._session.verify = settings.CRCZP_CONFIG.ssl_ca_certificate_verify or True

    def _url(self, path: str) -> str:
        return f'{self._base_url}{path}'

    def _raise_for_status(self, method: str, url: str, response: http_requests.Response) -> None:
        if response.status_code >= 400:
            raise NetbirdApiError(method, url, response.status_code, response.text)

    def _request(self, method: str, path: str, **kwargs: Any) -> http_requests.Response:
        url = self._url(path)
        try:
            response = self._session.request(method, url, timeout=self._timeout, **kwargs)
        except http_requests.RequestException as exc:
            # Catch the full requests exception hierarchy (ConnectionError,
            # Timeout, SSLError, ChunkedEncodingError, RetryError, …) so a
            # misbehaving Netbird endpoint cannot leak an uncaught exception
            # out of the client and kill the worker mid-cleanup.
            raise NetbirdApiError(method, url, 0, str(exc)) from exc
        return response

    # ---- Groups ----

    def create_group(self, name: str) -> str:
        """Create a group and return its ID."""
        path = '/api/groups'
        response = self._request('POST', path, json={'name': name, 'peers': [], 'resources': []})
        self._raise_for_status('POST', self._url(path), response)
        return str(response.json()['id'])

    def delete_group(self, group_id: str) -> None:
        """Delete a group, tolerating a 404 if it is already gone."""
        path = f'/api/groups/{group_id}'
        response = self._request('DELETE', path)
        if response.status_code == 404:
            return
        self._raise_for_status('DELETE', self._url(path), response)

    # ---- Setup Keys ----

    def create_setup_key(
        self,
        name: str,
        auto_group_ids: list[str],
        expires_in_seconds: int,
    ) -> tuple[str, str]:
        """Create a reusable setup key and return its (id, key) pair."""
        path = '/api/setup-keys'
        payload = {
            'name': name,
            'type': 'reusable',
            'expires_in': expires_in_seconds,
            'auto_groups': auto_group_ids,
            'usage_limit': 0,
            'ephemeral': False,
            'allow_extra_dns_labels': False,
        }
        response = self._request('POST', path, json=payload)
        self._raise_for_status('POST', self._url(path), response)
        data = response.json()
        return str(data['id']), str(data['key'])

    def delete_setup_key(self, key_id: str) -> None:
        """Delete a setup key, tolerating a 404 if it is already gone."""
        path = f'/api/setup-keys/{key_id}'
        response = self._request('DELETE', path)
        if response.status_code == 404:
            return
        self._raise_for_status('DELETE', self._url(path), response)

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
        path = '/api/routes'
        payload = {
            'description': description,
            'network_id': network_id,
            'enabled': True,
            'metric': 9999,
            'masquerade': True,
            'keep_route': False,
            'peer_groups': peer_group_ids,
            'network': cidr,
            'groups': client_group_ids,
        }
        response = self._request('POST', path, json=payload)
        self._raise_for_status('POST', self._url(path), response)
        return str(response.json()['id'])

    def delete_route(self, route_id: str) -> None:
        """Delete a route, tolerating a 404 if it is already gone."""
        path = f'/api/routes/{route_id}'
        response = self._request('DELETE', path)
        if response.status_code == 404:
            return
        self._raise_for_status('DELETE', self._url(path), response)

    # ---- Policies ----

    def create_policy(
        self,
        name: str,
        source_group_ids: list[str],
        destination_group_ids: list[str],
    ) -> str:
        """Create an access policy and return its ID."""
        path = '/api/policies'
        payload = {
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
        }
        response = self._request('POST', path, json=payload)
        self._raise_for_status('POST', self._url(path), response)
        return str(response.json()['id'])

    def delete_policy(self, policy_id: str) -> None:
        """Delete a policy, tolerating a 404 if it is already gone."""
        path = f'/api/policies/{policy_id}'
        response = self._request('DELETE', path)
        if response.status_code == 404:
            return
        self._raise_for_status('DELETE', self._url(path), response)

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
        path = '/api/dns/nameservers'
        payload = {
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
        }
        response = self._request('POST', path, json=payload)
        self._raise_for_status('POST', self._url(path), response)
        return str(response.json()['id'])

    def delete_nameserver_group(self, nameserver_group_id: str) -> None:
        """Delete a nameserver group, tolerating a 404 if it is already gone."""
        path = f'/api/dns/nameservers/{nameserver_group_id}'
        response = self._request('DELETE', path)
        if response.status_code == 404:
            return
        self._raise_for_status('DELETE', self._url(path), response)

    # ---- Peers ----

    def list_group_peer_ids(self, group_id: str) -> list[str]:
        """Return the peer IDs that are members of the given group.

        Used at teardown to find every agent (entrypoint host or trainee client)
        that registered into a sandbox group via its setup key, so the peers can
        be deleted from the control plane. A 404 (group already gone) yields [].
        """
        path = f'/api/groups/{group_id}'
        response = self._request('GET', path)
        if response.status_code == 404:
            return []
        self._raise_for_status('GET', self._url(path), response)
        # GET /api/groups/{id} returns peers as a list of {id, name} objects;
        # tolerate plain-string ids defensively.
        peers = response.json().get('peers') or []
        ids: list[str] = []
        for p in peers:
            if isinstance(p, dict) and p.get('id'):
                ids.append(p['id'])
            elif isinstance(p, str):
                ids.append(p)
        return ids

    def delete_peer(self, peer_id: str) -> None:
        """Delete a peer, tolerating a 404 if it is already gone."""
        path = f'/api/peers/{peer_id}'
        response = self._request('DELETE', path)
        if response.status_code == 404:
            return
        self._raise_for_status('DELETE', self._url(path), response)


def _read_service_user_pat(path: str) -> str:
    # Read fresh on every call so a rotated secret (volume-mounted Kubernetes
    # Secret) is picked up without restarting the service. Any failure to read
    # or decode the file (missing file, permission denied, non-UTF-8 contents,
    # …) is normalised to NetbirdConfigError so callers only have to guard a
    # single exception type. UnicodeDecodeError is a ValueError, not an OSError,
    # so it must be caught explicitly.
    try:
        with open(path, encoding='utf-8') as f:
            pat = f.read().strip()
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
