"""Tests for NetBird provisioning, teardown, and the sandbox VPN API view."""

# This module exercises NetBird's private helpers directly, uses locally
# defined fixtures, and injects side-effect-only fixtures, so the test-only
# diagnostics below are noise here.
# pylint: disable=protected-access,redefined-outer-name,unused-argument

from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest
from django.contrib.auth.models import AnonymousUser
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

from crczp.sandbox_common_lib.netbird_client import NetbirdApiError, NetbirdConfigError
from crczp.sandbox_instance_app.lib import netbird
from crczp.sandbox_instance_app.models import (
    Sandbox,
    SandboxNetbirdAccess,
    SandboxNetbirdResources,
)
from crczp.sandbox_instance_app.views import SandboxVpnView

pytestmark = pytest.mark.django_db

NETBIRD_MODULE = 'crczp.sandbox_instance_app.lib.netbird'


@dataclass
class FakeEntrypoint:  # pylint: disable=too-few-public-methods
    """Stand-in for a topology VPN entrypoint with a name and routes."""

    name: str
    routes: list[str]


@dataclass
class FakeDns:  # pylint: disable=too-few-public-methods
    """Stand-in for a topology vpn.dns block with servers and search domains."""

    servers: list[str]
    search_domains: list[str] | None = None


@pytest.fixture(autouse=True)
def quiet_log(mocker):
    """Silence the module logger for every test."""
    mocker.patch(f'{NETBIRD_MODULE}.LOG')


@pytest.fixture
def netbird_cfg(mocker):
    """Provide a minimal CRCZP_CONFIG with a netbird key-expiry setting."""
    # CRCZP_CONFIG is a yamlize Object whose attribute descriptor cannot be
    # safely patched in place, so swap the whole config object for the test.
    mocker.patch(
        f'{NETBIRD_MODULE}.settings.CRCZP_CONFIG',
        new=SimpleNamespace(netbird=SimpleNamespace(key_expiry_seconds=1209600)),
    )


class TestShortStackName:
    """Tests for the stack-name zero-padding stripper."""

    def test_strips_zero_padding(self):
        """The zero-padded pool/sandbox numbers are collapsed."""
        assert netbird._short_stack_name('kypo-p0000000123-s0000000045') == 'kypo-p123-s45'

    def test_keeps_single_zero_when_all_zeros(self):
        """An all-zero number collapses to a single zero."""
        assert netbird._short_stack_name('kypo-p0000000000-s0000000000') == 'kypo-p0-s0'

    def test_leaves_prefix_with_digits_untouched(self):
        """Digits in the prefix are not touched, only the suffix."""
        assert netbird._short_stack_name('demo01-p0000000007-s0000000001') == 'demo01-p7-s1'

    def test_returns_unchanged_when_no_suffix(self):
        """A name without the expected suffix is returned unchanged."""
        assert netbird._short_stack_name('something-else') == 'something-else'


class TestMakeNetworkId:
    """Tests for the NetBird network-id builder."""

    def test_sanitises_separators(self):
        """Slashes, dots and colons are removed from the id."""
        result = netbird._make_network_id('stack', 'host', '10.0.0.0/24')
        assert '/' not in result
        assert '.' not in result
        assert ':' not in result

    def test_sanitises_ipv6_colons(self):
        """IPv6 colons are removed from the id."""
        result = netbird._make_network_id('stack', 'host', 'fd00::/8')
        assert ':' not in result

    def test_truncated_to_max_len(self):
        """The id is truncated to Netbird's network_id character limit."""
        result = netbird._make_network_id('a' * 30, 'b' * 30, '10.0.0.0/24')
        assert len(result) <= netbird._NETBIRD_NETWORK_ID_MAX_LEN

    def test_host_name_truncated_to_prefix_len(self):
        """Only the configured prefix length of the host name is kept."""
        host_name = 'c' * 30
        result = netbird._make_network_id('stack', host_name, '10.0.0.0/24')
        kept_prefix = host_name[: netbird._HOST_NAME_ID_PREFIX_LEN]
        assert kept_prefix in result
        assert host_name not in result


class TestRouteListHelpers:
    """Tests for the comma-separated route id/cidr accessors on the model."""

    def test_get_route_id_list_empty_when_none(self):
        """An unset route_ids field yields an empty list."""
        assert SandboxNetbirdResources().get_route_id_list() == []

    def test_route_id_round_trip(self):
        """Route ids survive a set/get round trip."""
        nbr = SandboxNetbirdResources()
        nbr.set_route_id_list(['r1', 'r2'])
        assert nbr.route_ids == 'r1,r2'
        assert nbr.get_route_id_list() == ['r1', 'r2']

    def test_get_route_id_list_filters_empty_segments(self):
        """Empty comma segments are filtered out."""
        nbr = SandboxNetbirdResources()
        nbr.route_ids = 'r1,,r2,'
        assert nbr.get_route_id_list() == ['r1', 'r2']

    def test_get_route_cidr_list_empty_when_none(self):
        """An unset route_cidrs field yields an empty list."""
        assert SandboxNetbirdResources().get_route_cidr_list() == []

    def test_route_cidr_round_trip(self):
        """Route CIDRs survive a set/get round trip."""
        nbr = SandboxNetbirdResources()
        nbr.set_route_cidr_list(['10.0.0.0/24', '10.0.1.0/24'])
        assert nbr.route_cidrs == '10.0.0.0/24,10.0.1.0/24'
        assert nbr.get_route_cidr_list() == ['10.0.0.0/24', '10.0.1.0/24']


class TestGetVpnEntrypoints:
    """Tests for resolving a sandbox's VPN entrypoints from its definition."""

    def test_returns_entrypoints_when_present(self, mocker, sandbox):
        """Entrypoints declared on the definition's vpn block are returned."""
        ep = FakeEntrypoint('server', ['10.0.0.0/24'])
        mocker.patch(
            f'{NETBIRD_MODULE}.definitions.get_definition',
            return_value=SimpleNamespace(vpn=SimpleNamespace(entrypoints=[ep])),
        )
        assert netbird._get_vpn_entrypoints(sandbox) == [ep]

    def test_returns_empty_when_vpn_none(self, mocker, sandbox):
        """A null vpn attribute yields an empty list."""
        mocker.patch(
            f'{NETBIRD_MODULE}.definitions.get_definition',
            return_value=SimpleNamespace(vpn=None),
        )
        assert netbird._get_vpn_entrypoints(sandbox) == []

    def test_returns_empty_when_entrypoints_none(self, mocker, sandbox):
        """A vpn block with a null entrypoints attribute yields an empty list."""
        mocker.patch(
            f'{NETBIRD_MODULE}.definitions.get_definition',
            return_value=SimpleNamespace(vpn=SimpleNamespace(entrypoints=None)),
        )
        assert netbird._get_vpn_entrypoints(sandbox) == []

    def test_returns_empty_when_attribute_missing(self, mocker, sandbox):
        """A definition without a vpn attribute yields an empty list."""
        mocker.patch(
            f'{NETBIRD_MODULE}.definitions.get_definition',
            return_value=SimpleNamespace(),
        )
        assert netbird._get_vpn_entrypoints(sandbox) == []


class TestGetVpnDns:
    """Tests for resolving a sandbox's VPN DNS settings from its definition."""

    def test_returns_dns_when_present(self, mocker, sandbox):
        """The dns block declared on the definition's vpn block is returned."""
        dns = FakeDns(['10.0.0.5'])
        mocker.patch(
            f'{NETBIRD_MODULE}.definitions.get_definition',
            return_value=SimpleNamespace(vpn=SimpleNamespace(dns=dns)),
        )
        assert netbird._get_vpn_dns(sandbox) is dns

    def test_returns_none_when_vpn_none(self, mocker, sandbox):
        """A null vpn attribute yields None."""
        mocker.patch(
            f'{NETBIRD_MODULE}.definitions.get_definition',
            return_value=SimpleNamespace(vpn=None),
        )
        assert netbird._get_vpn_dns(sandbox) is None

    def test_returns_none_when_dns_absent(self, mocker, sandbox):
        """A vpn block without a dns attribute yields None."""
        mocker.patch(
            f'{NETBIRD_MODULE}.definitions.get_definition',
            return_value=SimpleNamespace(vpn=SimpleNamespace(dns=None)),
        )
        assert netbird._get_vpn_dns(sandbox) is None


class TestProvision:
    """Tests for provision_netbird_for_sandbox."""

    @pytest.fixture(autouse=True)
    def _default_no_dns(self, mocker):
        """Default to no VPN DNS settings; the DNS-specific tests re-patch this."""
        return mocker.patch(f'{NETBIRD_MODULE}._get_vpn_dns', return_value=None)

    def test_skipped_when_no_client(self, mocker, sandbox):
        """No client configured: provisioning is a no-op."""
        mocker.patch(f'{NETBIRD_MODULE}.get_netbird_client', return_value=None)
        spy = mocker.patch(f'{NETBIRD_MODULE}._get_vpn_entrypoints')

        netbird.provision_netbird_for_sandbox(sandbox)

        spy.assert_not_called()
        assert SandboxNetbirdResources.objects.filter(sandbox=sandbox).count() == 0

    def test_skipped_when_no_entrypoints(self, mocker, sandbox):
        """No entrypoints: nothing is created."""
        client = MagicMock()
        mocker.patch(f'{NETBIRD_MODULE}.get_netbird_client', return_value=client)
        mocker.patch(f'{NETBIRD_MODULE}._get_vpn_entrypoints', return_value=[])

        netbird.provision_netbird_for_sandbox(sandbox)

        client.create_group.assert_not_called()
        assert SandboxNetbirdResources.objects.filter(sandbox=sandbox).count() == 0

    def test_skipped_on_config_error(self, mocker, sandbox):
        """A config error building the client must not propagate or provision."""
        mocker.patch(
            f'{NETBIRD_MODULE}.get_netbird_client',
            side_effect=NetbirdConfigError('missing pat file'),
        )
        spy = mocker.patch(f'{NETBIRD_MODULE}._get_vpn_entrypoints')

        # Must not raise: a misconfigured PAT must never break allocation.
        netbird.provision_netbird_for_sandbox(sandbox)

        spy.assert_not_called()
        assert SandboxNetbirdResources.objects.filter(sandbox=sandbox).count() == 0

    def test_skipped_when_entrypoint_lookup_fails(self, mocker, sandbox):
        """A failing definition fetch must not propagate or provision."""
        client = MagicMock()
        mocker.patch(f'{NETBIRD_MODULE}.get_netbird_client', return_value=client)
        mocker.patch(
            f'{NETBIRD_MODULE}._get_vpn_entrypoints',
            side_effect=RuntimeError('git fetch failed'),
        )

        # Must not raise: a transient definition error must never break allocation.
        netbird.provision_netbird_for_sandbox(sandbox)

        client.create_group.assert_not_called()
        assert SandboxNetbirdResources.objects.filter(sandbox=sandbox).count() == 0

    def test_entry_point_never_raises_on_unexpected_error(self, mocker, sandbox):
        """The public entry point swallows unexpected errors.

        It is the target of the provisioning job that the user-ansible stage
        depends on; a raised exception would fail the job and wedge that stage.
        """
        mocker.patch(
            f'{NETBIRD_MODULE}._provision_netbird_for_sandbox',
            side_effect=RuntimeError('unexpected db error'),
        )

        # Must not raise.
        netbird.provision_netbird_for_sandbox(sandbox)

    def test_creates_all_resources(self, mocker, sandbox, netbird_cfg):
        """Happy path: access and per-entrypoint resources are all created."""
        client = MagicMock()
        # The shared access group/key are created first, then the per-entrypoint
        # host group/key.
        client.create_group.side_effect = ['access-grp', 'host-grp']
        client.create_setup_key.side_effect = [
            ('access-key-id', 'access-key-val'),
            ('host-key-id', 'host-key-val'),
        ]
        client.create_route.return_value = 'route-1'
        client.create_policy.return_value = 'pol-1'
        mocker.patch(f'{NETBIRD_MODULE}.get_netbird_client', return_value=client)
        mocker.patch(
            f'{NETBIRD_MODULE}._get_vpn_entrypoints',
            return_value=[FakeEntrypoint('server', ['10.0.0.0/24'])],
        )

        netbird.provision_netbird_for_sandbox(sandbox)

        access = SandboxNetbirdAccess.objects.get(sandbox=sandbox)
        assert access.access_group_id == 'access-grp'
        assert access.access_setup_key_id == 'access-key-id'
        assert access.access_setup_key_value == 'access-key-val'

        nbr = SandboxNetbirdResources.objects.get(sandbox=sandbox, entrypoint_host_name='server')
        assert nbr.host_group_id == 'host-grp'
        assert nbr.host_setup_key_id == 'host-key-id'
        assert nbr.host_setup_key_value == 'host-key-val'
        assert nbr.get_route_id_list() == ['route-1']
        assert nbr.get_route_cidr_list() == ['10.0.0.0/24']
        assert nbr.policy_id == 'pol-1'

        assert client.create_group.call_count == 2
        stack_name = netbird._short_stack_name(sandbox.allocation_unit.get_stack_name())
        client.create_route.assert_called_once_with(
            network_id=netbird._make_network_id(stack_name, 'server', '10.0.0.0/24'),
            cidr='10.0.0.0/24',
            peer_group_ids=['host-grp'],
            client_group_ids=['access-grp'],
            description=f'{stack_name} server route 10.0.0.0/24',
        )
        client.create_policy.assert_called_once_with(
            name=f'{stack_name}-server-policy',
            source_group_ids=['access-grp'],
            destination_group_ids=['host-grp'],
        )
        # No vpn.dns in this topology, so no nameserver group is created.
        client.create_nameserver_group.assert_not_called()
        assert access.dns_nameserver_group_id is None

    def test_partial_failure_persists_row(self, mocker, sandbox, netbird_cfg):
        """A failing entrypoint is caught and its partial row persisted."""
        client = MagicMock()
        # Access provisions fully; the entrypoint then fails on its host key.
        client.create_group.side_effect = ['access-grp', 'host-grp']
        client.create_setup_key.side_effect = [
            ('access-key-id', 'access-key-val'),
            NetbirdApiError('POST', 'url', 500, 'fail'),
        ]
        mocker.patch(f'{NETBIRD_MODULE}.get_netbird_client', return_value=client)
        mocker.patch(
            f'{NETBIRD_MODULE}._get_vpn_entrypoints',
            return_value=[FakeEntrypoint('server', ['10.0.0.0/24'])],
        )

        # Must not raise: a failing entrypoint is caught and logged.
        netbird.provision_netbird_for_sandbox(sandbox)

        nbr = SandboxNetbirdResources.objects.get(sandbox=sandbox, entrypoint_host_name='server')
        assert nbr.host_group_id == 'host-grp'
        assert nbr.host_setup_key_id is None
        assert nbr.policy_id is None

    def test_access_failure_skips_entrypoints(self, mocker, sandbox, netbird_cfg):
        """If the shared access group cannot be created, no entrypoint is provisioned."""
        client = MagicMock()
        client.create_group.side_effect = NetbirdApiError('POST', 'url', 500, 'fail')
        mocker.patch(f'{NETBIRD_MODULE}.get_netbird_client', return_value=client)
        mocker.patch(
            f'{NETBIRD_MODULE}._get_vpn_entrypoints',
            return_value=[FakeEntrypoint('server', ['10.0.0.0/24'])],
        )

        netbird.provision_netbird_for_sandbox(sandbox)

        # Access group creation failed, so the host group is never attempted.
        client.create_group.assert_called_once()
        client.create_setup_key.assert_not_called()
        assert SandboxNetbirdResources.objects.filter(sandbox=sandbox).count() == 0

    def test_start_guard_skips_when_sandbox_deleted(self, mocker, sandbox, netbird_cfg):
        """Start guard: sandbox row absent before any cloud calls → no create_* calls."""
        client = MagicMock()
        mocker.patch(f'{NETBIRD_MODULE}.get_netbird_client', return_value=client)
        mocker.patch(
            f'{NETBIRD_MODULE}._get_vpn_entrypoints',
            return_value=[FakeEntrypoint('server', ['10.0.0.0/24'])],
        )
        # Delete the sandbox so the start guard fires.
        sandbox.delete()

        netbird.provision_netbird_for_sandbox(sandbox)

        client.create_group.assert_not_called()
        client.create_setup_key.assert_not_called()
        client.create_route.assert_not_called()
        client.create_policy.assert_not_called()

    def test_end_guard_tears_down_when_sandbox_deleted_mid_provision(
        self, mocker, sandbox, netbird_cfg
    ):
        """End guard: sandbox deleted while provisioning → delete_* called for created resources."""
        client = MagicMock()
        client.create_group.side_effect = ['access-grp', 'host-grp']
        client.create_setup_key.side_effect = [
            ('access-key-id', 'access-key-val'),
            ('host-key-id', 'host-key-val'),
        ]
        client.create_route.return_value = 'route-1'
        client.create_policy.return_value = 'pol-1'
        client.list_group_peer_ids.return_value = []
        mocker.patch(f'{NETBIRD_MODULE}.get_netbird_client', return_value=client)
        mocker.patch(
            f'{NETBIRD_MODULE}._get_vpn_entrypoints',
            return_value=[FakeEntrypoint('server', ['10.0.0.0/24'])],
        )

        # Simulate the sandbox being deleted mid-provision: the start guard sees
        # it as existing (True), but the end guard sees it as gone (False).
        exists_results = iter([True, False])
        mocker.patch(
            f'{NETBIRD_MODULE}.Sandbox.objects.filter',
            side_effect=lambda **_kw: type(
                '_QS', (), {'exists': lambda self: next(exists_results)}
            )(),
        )

        netbird.provision_netbird_for_sandbox(sandbox)

        # The provisioning ran and then the end guard triggered teardown of both
        # the entrypoint and the shared access resources.
        client.delete_policy.assert_called_once_with('pol-1')
        client.delete_route.assert_called_once_with('route-1')
        client.delete_setup_key.assert_any_call('host-key-id')
        client.delete_setup_key.assert_any_call('access-key-id')
        client.delete_group.assert_any_call('host-grp')
        client.delete_group.assert_any_call('access-grp')

    def test_end_guard_tears_down_access_group_when_row_deleted_mid_provision(
        self, mocker, sandbox, netbird_cfg
    ):
        """Regression: the access group is torn down even if its DB row is gone.

        If the sandbox is cascade-deleted mid-provision, the SandboxNetbirdAccess
        row disappears while a Netbird object already exists. The error path must
        keep the in-memory handle (not re-read the deleted row as None) so the end
        guard can still delete the created access group rather than orphan it.
        """
        client = MagicMock()
        client.create_group.side_effect = ['access-grp', 'host-grp']
        client.list_group_peer_ids.return_value = []

        def _delete_row_then_fail(*_args, **_kwargs):
            # The access group already exists in Netbird; now simulate the
            # sandbox's cascade-delete removing the access row mid-provision.
            SandboxNetbirdAccess.objects.filter(sandbox=sandbox).delete()
            raise NetbirdApiError('POST', 'url', 500, 'fail')

        client.create_setup_key.side_effect = _delete_row_then_fail
        mocker.patch(f'{NETBIRD_MODULE}.get_netbird_client', return_value=client)
        mocker.patch(
            f'{NETBIRD_MODULE}._get_vpn_entrypoints',
            return_value=[FakeEntrypoint('server', ['10.0.0.0/24'])],
        )

        # Start guard sees the sandbox (True); end guard sees it gone (False).
        exists_results = iter([True, False])
        mocker.patch(
            f'{NETBIRD_MODULE}.Sandbox.objects.filter',
            side_effect=lambda **_kw: type(
                '_QS', (), {'exists': lambda self: next(exists_results)}
            )(),
        )

        netbird.provision_netbird_for_sandbox(sandbox)

        # The created access group is torn down from the retained handle even
        # though its DB row was deleted before the error handler ran.
        client.delete_group.assert_any_call('access-grp')

    def test_creates_dns_primary_nameserver_group(self, mocker, sandbox, netbird_cfg):
        """vpn.dns without search domains creates a primary nameserver group."""
        client = MagicMock()
        client.create_group.side_effect = ['access-grp', 'host-grp']
        client.create_setup_key.side_effect = [('ak-id', 'ak'), ('hk-id', 'hk')]
        client.create_route.return_value = 'route-1'
        client.create_policy.return_value = 'pol-1'
        client.create_nameserver_group.return_value = 'ns-1'
        mocker.patch(f'{NETBIRD_MODULE}.get_netbird_client', return_value=client)
        mocker.patch(
            f'{NETBIRD_MODULE}._get_vpn_entrypoints',
            return_value=[FakeEntrypoint('server', ['10.0.0.0/24'])],
        )
        mocker.patch(f'{NETBIRD_MODULE}._get_vpn_dns', return_value=FakeDns(['10.0.0.5']))

        netbird.provision_netbird_for_sandbox(sandbox)

        access = SandboxNetbirdAccess.objects.get(sandbox=sandbox)
        assert access.dns_nameserver_group_id == 'ns-1'
        stack_name = netbird._short_stack_name(sandbox.allocation_unit.get_stack_name())
        client.create_nameserver_group.assert_called_once_with(
            name=f'{stack_name}-dns',
            servers=['10.0.0.5'],
            distribution_group_ids=['access-grp'],
            primary=True,
            domains=[],
            search_domains_enabled=False,
            description=f'{stack_name} DNS',
        )

    def test_creates_dns_domain_scoped_nameserver_group(self, mocker, sandbox, netbird_cfg):
        """vpn.dns with search domains creates a non-primary, domain-scoped group."""
        client = MagicMock()
        client.create_group.side_effect = ['access-grp', 'host-grp']
        client.create_setup_key.side_effect = [('ak-id', 'ak'), ('hk-id', 'hk')]
        client.create_route.return_value = 'route-1'
        client.create_policy.return_value = 'pol-1'
        client.create_nameserver_group.return_value = 'ns-1'
        mocker.patch(f'{NETBIRD_MODULE}.get_netbird_client', return_value=client)
        mocker.patch(
            f'{NETBIRD_MODULE}._get_vpn_entrypoints',
            return_value=[FakeEntrypoint('server', ['10.0.0.0/24'])],
        )
        mocker.patch(
            f'{NETBIRD_MODULE}._get_vpn_dns',
            return_value=FakeDns(['10.0.0.5', '10.0.0.6'], ['sandbox.local']),
        )

        netbird.provision_netbird_for_sandbox(sandbox)

        access = SandboxNetbirdAccess.objects.get(sandbox=sandbox)
        assert access.dns_nameserver_group_id == 'ns-1'
        stack_name = netbird._short_stack_name(sandbox.allocation_unit.get_stack_name())
        client.create_nameserver_group.assert_called_once_with(
            name=f'{stack_name}-dns',
            servers=['10.0.0.5', '10.0.0.6'],
            distribution_group_ids=['access-grp'],
            primary=False,
            domains=['sandbox.local'],
            search_domains_enabled=True,
            description=f'{stack_name} DNS',
        )

    def test_dns_failure_does_not_break_entrypoints(self, mocker, sandbox, netbird_cfg):
        """A failing nameserver-group create is contained; the entrypoint still provisions."""
        client = MagicMock()
        client.create_group.side_effect = ['access-grp', 'host-grp']
        client.create_setup_key.side_effect = [('ak-id', 'ak'), ('hk-id', 'hk')]
        client.create_route.return_value = 'route-1'
        client.create_policy.return_value = 'pol-1'
        client.create_nameserver_group.side_effect = NetbirdApiError('POST', 'url', 500, 'fail')
        mocker.patch(f'{NETBIRD_MODULE}.get_netbird_client', return_value=client)
        mocker.patch(
            f'{NETBIRD_MODULE}._get_vpn_entrypoints',
            return_value=[FakeEntrypoint('server', ['10.0.0.0/24'])],
        )
        mocker.patch(f'{NETBIRD_MODULE}._get_vpn_dns', return_value=FakeDns(['10.0.0.5']))

        # Must not raise: a failing DNS provision is caught and logged.
        netbird.provision_netbird_for_sandbox(sandbox)

        nbr = SandboxNetbirdResources.objects.get(sandbox=sandbox, entrypoint_host_name='server')
        assert nbr.policy_id == 'pol-1'
        access = SandboxNetbirdAccess.objects.get(sandbox=sandbox)
        assert access.dns_nameserver_group_id is None

    def test_dns_provisioned_without_entrypoints(self, mocker, sandbox, netbird_cfg):
        """vpn.dns with no entrypoints still creates the access group and nameserver group."""
        client = MagicMock()
        client.create_group.return_value = 'access-grp'
        client.create_setup_key.return_value = ('ak-id', 'ak')
        client.create_nameserver_group.return_value = 'ns-1'
        mocker.patch(f'{NETBIRD_MODULE}.get_netbird_client', return_value=client)
        mocker.patch(f'{NETBIRD_MODULE}._get_vpn_entrypoints', return_value=[])
        mocker.patch(f'{NETBIRD_MODULE}._get_vpn_dns', return_value=FakeDns(['10.0.0.5']))

        netbird.provision_netbird_for_sandbox(sandbox)

        access = SandboxNetbirdAccess.objects.get(sandbox=sandbox)
        assert access.access_group_id == 'access-grp'
        assert access.dns_nameserver_group_id == 'ns-1'
        # No entrypoints, so no per-host policy or resources rows.
        client.create_policy.assert_not_called()
        assert SandboxNetbirdResources.objects.filter(sandbox=sandbox).count() == 0


class TestDestroy:
    """Tests for destroy_netbird_for_sandbox."""

    @staticmethod
    def _create_full_resources(sandbox: Sandbox) -> SandboxNetbirdResources:
        SandboxNetbirdAccess.objects.create(
            sandbox=sandbox,
            access_group_id='access-grp',
            access_setup_key_id='access-key',
            access_setup_key_value='akv',
        )
        nbr = SandboxNetbirdResources.objects.create(
            sandbox=sandbox,
            entrypoint_host_name='server',
            host_group_id='host-grp',
            host_setup_key_id='host-key',
            host_setup_key_value='hkv',
            policy_id='pol-1',
        )
        nbr.set_route_id_list(['route-1', 'route-2'])
        nbr.set_route_cidr_list(['10.0.0.0/24'])
        nbr.save()
        return nbr

    def test_skipped_when_no_client(self, mocker, sandbox):
        """No client configured: resources are left in place."""
        self._create_full_resources(sandbox)
        mocker.patch(f'{NETBIRD_MODULE}.get_netbird_client', return_value=None)

        netbird.destroy_netbird_for_sandbox(sandbox)

        assert SandboxNetbirdResources.objects.filter(sandbox=sandbox).exists()

    def test_no_op_when_no_resources(self, mocker, sandbox):
        """Nothing to delete: no API calls are made."""
        client = MagicMock()
        mocker.patch(f'{NETBIRD_MODULE}.get_netbird_client', return_value=client)

        netbird.destroy_netbird_for_sandbox(sandbox)

        client.delete_policy.assert_not_called()
        client.delete_group.assert_not_called()

    def test_skipped_on_config_error_keeps_rows(self, mocker, sandbox):
        """A config error building the client must not propagate or drop rows."""
        self._create_full_resources(sandbox)
        mocker.patch(
            f'{NETBIRD_MODULE}.get_netbird_client',
            side_effect=NetbirdConfigError('missing pat file'),
        )

        # Must not raise: cleanup must proceed even if Netbird is misconfigured.
        netbird.destroy_netbird_for_sandbox(sandbox)

        assert SandboxNetbirdResources.objects.filter(sandbox=sandbox).exists()
        assert SandboxNetbirdAccess.objects.filter(sandbox=sandbox).exists()

    def test_stops_when_time_budget_exceeded(self, mocker, sandbox):
        """Once the budget is exceeded mid-teardown, no further cloud calls run."""
        self._create_full_resources(sandbox)
        client = MagicMock()
        client.list_group_peer_ids.return_value = []
        mocker.patch(f'{NETBIRD_MODULE}.get_netbird_client', return_value=client)
        mocker.patch(f'{NETBIRD_MODULE}._teardown_budget_seconds', return_value=100)

        # A controllable monotonic clock: the deadline is 0 + 100 = 100, and the
        # very first cloud call (delete_policy) pushes the clock past it, so the
        # deadline is checked before every subsequent call and stops the teardown.
        now = [0.0]
        mocker.patch(f'{NETBIRD_MODULE}.time.monotonic', side_effect=lambda: now[0])
        client.delete_policy.side_effect = lambda *_a, **_k: now.__setitem__(0, 1000.0)

        netbird.destroy_netbird_for_sandbox(sandbox)

        # The first call happened; everything after the budget expired is skipped.
        client.delete_policy.assert_called_once_with('pol-1')
        client.delete_route.assert_not_called()
        client.delete_setup_key.assert_not_called()  # neither host nor access key
        client.delete_group.assert_not_called()
        # The shared access teardown never ran, so its row remains for cascade.
        assert SandboxNetbirdAccess.objects.filter(sandbox=sandbox).exists()
        assert SandboxNetbirdResources.objects.filter(sandbox=sandbox).exists()

    def test_budget_does_not_cut_short_a_healthy_teardown(self, mocker, sandbox):
        """With a normal budget and a fast endpoint, everything is torn down."""
        self._create_full_resources(sandbox)
        client = MagicMock()
        client.list_group_peer_ids.return_value = []
        mocker.patch(f'{NETBIRD_MODULE}.get_netbird_client', return_value=client)

        netbird.destroy_netbird_for_sandbox(sandbox)

        client.delete_policy.assert_called_once_with('pol-1')
        client.delete_setup_key.assert_has_calls([call('host-key'), call('access-key')])
        client.delete_group.assert_has_calls([call('host-grp'), call('access-grp')])
        assert not SandboxNetbirdResources.objects.filter(sandbox=sandbox).exists()
        assert not SandboxNetbirdAccess.objects.filter(sandbox=sandbox).exists()

    def test_deletes_all_resources_and_row(self, mocker, sandbox):
        """All resources are deleted in order and the rows removed."""
        self._create_full_resources(sandbox)
        client = MagicMock()
        client.list_group_peer_ids.return_value = []
        mocker.patch(f'{NETBIRD_MODULE}.get_netbird_client', return_value=client)

        netbird.destroy_netbird_for_sandbox(sandbox)

        client.delete_policy.assert_called_once_with('pol-1')
        client.delete_route.assert_has_calls([call('route-1'), call('route-2')])
        # Entrypoint host key first, then the shared access key.
        client.delete_setup_key.assert_has_calls([call('host-key'), call('access-key')])
        client.delete_group.assert_has_calls([call('host-grp'), call('access-grp')])
        # No DNS nameserver group was provisioned for these resources.
        client.delete_nameserver_group.assert_not_called()
        assert not SandboxNetbirdResources.objects.filter(sandbox=sandbox).exists()
        assert not SandboxNetbirdAccess.objects.filter(sandbox=sandbox).exists()

    def test_deletes_dns_nameserver_group_before_access_group(self, mocker, sandbox):
        """A provisioned nameserver group is deleted before the access group it targets."""
        self._create_full_resources(sandbox)
        access = SandboxNetbirdAccess.objects.get(sandbox=sandbox)
        access.dns_nameserver_group_id = 'ns-1'
        access.save()
        client = MagicMock()
        client.list_group_peer_ids.return_value = []
        mocker.patch(f'{NETBIRD_MODULE}.get_netbird_client', return_value=client)

        netbird.destroy_netbird_for_sandbox(sandbox)

        client.delete_nameserver_group.assert_called_once_with('ns-1')
        # The nameserver group references the access group as its distribution
        # group, so it must be deleted before the access group itself.
        order = client.mock_calls.index(call.delete_nameserver_group('ns-1'))
        assert order < client.mock_calls.index(call.delete_group('access-grp'))
        assert not SandboxNetbirdAccess.objects.filter(sandbox=sandbox).exists()

    def test_tolerates_api_error_and_still_removes_row(self, mocker, sandbox):
        """A NetbirdApiError during teardown still removes the records."""
        self._create_full_resources(sandbox)
        client = MagicMock()
        client.list_group_peer_ids.return_value = []
        client.delete_policy.side_effect = NetbirdApiError('DELETE', 'url', 500, 'fail')
        mocker.patch(f'{NETBIRD_MODULE}.get_netbird_client', return_value=client)

        netbird.destroy_netbird_for_sandbox(sandbox)

        # Remaining resources are still cleaned up and the records are removed.
        client.delete_group.assert_has_calls([call('host-grp'), call('access-grp')])
        assert not SandboxNetbirdResources.objects.filter(sandbox=sandbox).exists()
        assert not SandboxNetbirdAccess.objects.filter(sandbox=sandbox).exists()

    def test_tolerates_unexpected_exception_keeps_row(self, mocker, sandbox):
        """An unexpected exception is contained but leaves the row for retry."""
        self._create_full_resources(sandbox)
        client = MagicMock()
        client.list_group_peer_ids.return_value = []
        # A non-NetbirdApiError is not swallowed inside _destroy_single_entrypoint;
        # the per-entrypoint guard in destroy_netbird_for_sandbox must still
        # prevent it from propagating, but the row is left for a later retry.
        client.delete_policy.side_effect = ValueError('boom')
        mocker.patch(f'{NETBIRD_MODULE}.get_netbird_client', return_value=client)

        netbird.destroy_netbird_for_sandbox(sandbox)

        assert SandboxNetbirdResources.objects.filter(sandbox=sandbox).exists()

    def test_deletes_peers_in_each_group(self, mocker, sandbox):
        """Every group's peers are deleted before the group itself."""
        self._create_full_resources(sandbox)
        client = MagicMock()
        peer_map = {'host-grp': ['hp1'], 'access-grp': ['ap1', 'ap2']}
        client.list_group_peer_ids.side_effect = lambda gid: peer_map[gid]
        mocker.patch(f'{NETBIRD_MODULE}.get_netbird_client', return_value=client)

        netbird.destroy_netbird_for_sandbox(sandbox)

        client.delete_peer.assert_any_call('hp1')
        client.delete_peer.assert_any_call('ap1')
        client.delete_peer.assert_any_call('ap2')
        assert client.delete_peer.call_count == 3
        assert not SandboxNetbirdResources.objects.filter(sandbox=sandbox).exists()
        assert not SandboxNetbirdAccess.objects.filter(sandbox=sandbox).exists()

        # Peers of a group must be deleted before the group itself.
        all_calls = client.mock_calls
        call_names = [(c[0], c[1][0] if c[1] else None) for c in all_calls]
        hp1_idx = next(
            i for i, (n, a) in enumerate(call_names) if n == 'delete_peer' and a == 'hp1'
        )
        host_grp_idx = next(
            i for i, (n, a) in enumerate(call_names) if n == 'delete_group' and a == 'host-grp'
        )
        ap1_idx = next(
            i for i, (n, a) in enumerate(call_names) if n == 'delete_peer' and a == 'ap1'
        )
        access_grp_idx = next(
            i for i, (n, a) in enumerate(call_names) if n == 'delete_group' and a == 'access-grp'
        )
        assert hp1_idx < host_grp_idx
        assert ap1_idx < access_grp_idx


class TestSandboxVpnView:
    """Tests for the sandbox VPN API view."""

    @pytest.fixture(autouse=True)
    def set_up(self, mocker, sandbox):
        """Patch sandbox lookup and the client management URL for the view."""
        # pylint: disable-next=attribute-defined-outside-init
        self.factory = APIRequestFactory()
        mocker.patch('crczp.sandbox_instance_app.views.sandboxes.get_sandbox', return_value=sandbox)
        mocker.patch(
            'crczp.sandbox_instance_app.views.get_client_management_url',
            return_value='https://client.example.com',
        )

    def _call(self, sandbox: Sandbox) -> Response:
        request = self.factory.get(f'/sandboxes/{sandbox.id}/vpn')
        request.user = AnonymousUser()
        view = SandboxVpnView()
        view.kwargs = {'sandbox_uuid': sandbox.id}
        return view.get(request)

    def test_returns_single_key_and_union_of_routes(self, sandbox):
        """The view returns the shared key and the de-duplicated route union."""
        SandboxNetbirdAccess.objects.create(
            sandbox=sandbox,
            access_setup_key_value='access-key-val',
        )
        first = SandboxNetbirdResources.objects.create(
            sandbox=sandbox, entrypoint_host_name='server'
        )
        first.set_route_cidr_list(['10.0.0.0/24', '10.0.1.0/24'])
        first.save()
        second = SandboxNetbirdResources.objects.create(
            sandbox=sandbox, entrypoint_host_name='gateway'
        )
        # Overlapping CIDR must be de-duplicated in the union.
        second.set_route_cidr_list(['10.0.1.0/24', '10.0.2.0/24'])
        second.save()

        response = self._call(sandbox)

        assert response.status_code == 200
        assert response.data == {
            'management_url': 'https://client.example.com',
            'setup_key': 'access-key-val',
            'routes': ['10.0.0.0/24', '10.0.1.0/24', '10.0.2.0/24'],
            'command': (
                'netbird up --management-url https://client.example.com --setup-key access-key-val'
            ),
        }

    def test_setup_key_null_when_access_not_ready(self, sandbox):
        """A missing setup key yields null and no leaked routes."""
        # Access row exists but the key is not provisioned yet: no routes leak.
        SandboxNetbirdAccess.objects.create(sandbox=sandbox, access_setup_key_value=None)
        nbr = SandboxNetbirdResources.objects.create(sandbox=sandbox, entrypoint_host_name='server')
        nbr.set_route_cidr_list(['10.0.0.0/24'])
        nbr.save()

        response = self._call(sandbox)

        assert response.status_code == 200
        assert response.data == {
            'management_url': 'https://client.example.com',
            'setup_key': None,
            'routes': [],
            'command': None,
        }

    def test_command_shell_quotes_setup_key(self, sandbox):
        """A setup key with shell-special characters is quoted in the command."""
        SandboxNetbirdAccess.objects.create(
            sandbox=sandbox,
            access_setup_key_value='ab cd$x',
        )

        response = self._call(sandbox)

        assert response.status_code == 200
        assert response.data['command'] == (
            "netbird up --management-url https://client.example.com --setup-key 'ab cd$x'"
        )

    def test_returns_empty_when_no_resources(self, sandbox):
        """With no resources the view returns a null key, empty routes and no command."""
        response = self._call(sandbox)
        assert response.status_code == 200
        assert response.data == {
            'management_url': 'https://client.example.com',
            'setup_key': None,
            'routes': [],
            'command': None,
        }
