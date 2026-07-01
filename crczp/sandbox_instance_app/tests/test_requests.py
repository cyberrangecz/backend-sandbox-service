"""Tests for sandbox allocation and cleanup request logic."""

from functools import partial
from typing import Any
from unittest.mock import call

import pytest
from django.db.models import ObjectDoesNotExist
from django.utils import timezone

from crczp.sandbox_common_lib import exceptions as api_exceptions
from crczp.sandbox_instance_app.lib import requests
from crczp.sandbox_instance_app.models import (
    AllocationRequest,
    CleanupRequest,
    Sandbox,
    SandboxAllocationUnit,
)

pytestmark = pytest.mark.django_db


class TestAllocationRequest:
    """Tests for sandbox allocation request creation and management."""

    @pytest.fixture(autouse=True)
    def set_up(self, mocker):  # pylint: disable=attribute-defined-outside-init
        """Patch the AllocationRequestHandler for isolation."""
        self.handler = mocker.patch(
            'crczp.sandbox_instance_app.lib.requests.request_handlers.AllocationRequestHandler'
        )

    def test_create_allocation_requests_success(self, pool, created_by, mocker):
        """Test that allocation requests are created and enqueued on commit."""
        fake_on_commit = mocker.patch('django.db.transaction.on_commit')
        requests.create_allocations_requests(pool, 2, created_by)
        created_units = list(SandboxAllocationUnit.objects.filter(pool=pool))

        expected_partial = partial(
            self.handler.return_value.enqueue_request, created_units, created_by
        )
        actual_partial = fake_on_commit.call_args.args[0]

        # Assert the correct transaction.on_commit args are passed
        assert expected_partial.func == actual_partial.func
        assert expected_partial.args == actual_partial.args
        assert expected_partial.keywords == actual_partial.keywords

    def test_create_allocation_requests_creates_request_synchronously(
        self, pool, created_by, mocker
    ):
        """The AllocationRequest must exist as soon as create_allocations_requests
        returns — before the worker runs — so the listing endpoint never serves a
        unit with allocation_request=null (which the frontend shows as an error)."""
        mocker.patch('django.db.transaction.on_commit')

        units = requests.create_allocations_requests(pool, 3, created_by)

        assert len(units) == 3
        for unit in units:
            assert AllocationRequest.objects.filter(allocation_unit=unit).exists()

    def test_cancel_allocation_request_success(self, allocation_request_started):
        """Test that cancellation delegates to the handler correctly."""
        requests.cancel_allocation_request(allocation_request_started)

        self.handler.return_value.cancel_request.assert_called_once_with(allocation_request_started)

    def test_get_allocation_request_stages_state(
        self, allocation_request, allocation_stage_networking_started, allocation_stage_user
    ):
        """Test that allocation stage states are returned in the correct order."""
        stages_state = requests.get_allocation_request_stages_state(allocation_request)

        assert stages_state == [
            requests.StageState.FINISHED.value,
            requests.StageState.RUNNING.value,
            requests.StageState.IN_QUEUE.value,
        ]

    def test_get_allocation_request_stages_state_fail(
        self, allocation_request, allocation_stage_networking_started, allocation_stage_user
    ):
        """Test that failed allocation stages are reported as FAILED."""
        allocation_stage_networking_started.failed = True
        allocation_stage_networking_started.end = timezone.now()
        allocation_stage_user.failed = True
        allocation_stage_user.end = timezone.now()

        stages_state = requests.get_allocation_request_stages_state(allocation_request)

        assert stages_state == [
            requests.StageState.FINISHED.value,
            requests.StageState.FAILED.value,
            requests.StageState.FAILED.value,
        ]


class TestCleanupRequest:  # pylint: disable=too-many-public-methods
    """Tests for sandbox cleanup request creation, cancellation, and stage states."""

    @pytest.fixture(autouse=True)
    def set_up(self, mocker):  # pylint: disable=attribute-defined-outside-init
        """Patch the CleanupRequestHandler and LOG for isolation."""
        mocker.patch('crczp.sandbox_instance_app.lib.requests.LOG')
        self.handler = mocker.patch(
            'crczp.sandbox_instance_app.lib.requests.request_handlers.CleanupRequestHandler'
        )

    def assert_cleanup_request_success(
        self, allocation_unit: SandboxAllocationUnit, force: bool = False
    ) -> None:
        """Assert a cleanup request is created successfully and sandbox is deleted."""
        requests.create_cleanup_requests([allocation_unit], force)

        with pytest.raises(ObjectDoesNotExist):
            assert Sandbox.objects.get(pk=allocation_unit.sandbox.id)

        self.handler.return_value.enqueue_request.assert_called_once_with(allocation_unit)

    def assert_cleanup_request_failed(self, allocation_unit: SandboxAllocationUnit) -> None:
        """Assert that creating a cleanup request raises ValidationError."""
        with pytest.raises(api_exceptions.ValidationError):
            requests.create_cleanup_request(allocation_unit)

        with pytest.raises(ObjectDoesNotExist):
            assert CleanupRequest.objects.get(pk=allocation_unit.id)
        self.handler.assert_not_called()

    def assert_cleanup_ongoing_force_skipped(self, allocation_unit: SandboxAllocationUnit) -> None:
        """Assert that a force cleanup is skipped when one is already ongoing."""
        requests.create_cleanup_request_force(allocation_unit, False)

        self.handler.assert_not_called()

    def assert_multiple_cleanup_requests_success(self, allocation_units: Any) -> None:
        """Assert that cleanup requests are created for all units and sandboxes deleted."""
        for allocation_unit in allocation_units:
            with pytest.raises(ObjectDoesNotExist):
                assert Sandbox.objects.get(pk=allocation_unit.sandbox.id)

        self.handler.return_value.enqueue_request.assert_has_calls([
            call(allocation_unit) for allocation_unit in allocation_units
        ])

    def test_create_cleanup_request_success(self, sandbox_finished):
        """Test cleanup request creation for a finished sandbox."""
        allocation_unit = sandbox_finished.allocation_unit
        self.assert_cleanup_request_success(allocation_unit)

    def test_create_cleanup_request_failed_locked_sandbox(self, sandbox_lock):
        """Test that cleanup request fails for a locked sandbox."""
        allocation_unit = sandbox_lock.sandbox.allocation_unit
        self.assert_cleanup_request_failed(allocation_unit)
        assert Sandbox.objects.get(pk=sandbox_lock.sandbox.id)

    def test_create_cleanup_request_force_locked_sandbox(self, sandbox_lock):
        """Test that a force cleanup request succeeds even for a locked sandbox."""
        allocation_unit = sandbox_lock.sandbox.allocation_unit
        self.assert_cleanup_request_success(allocation_unit, True)

    def test_create_cleanup_request_failed_active_allocation_request(
        self, allocation_stage_user_started
    ):
        """Test that cleanup fails when an allocation is still active."""
        allocation_unit = allocation_stage_user_started.allocation_request.allocation_unit
        self.assert_cleanup_request_failed(allocation_unit)

    def test_create_cleanup_request_force_active_allocation_request(
        self, mocker, allocation_stage_user_started
    ):
        """Test that a force cleanup succeeds even when allocation is still active."""
        allocation_unit = allocation_stage_user_started.allocation_request.allocation_unit
        mocker.patch(
            'crczp.sandbox_instance_app.lib.requests.request_handlers.AllocationRequestHandler'
        )
        self.assert_cleanup_request_success(allocation_unit, True)

    def test_create_cleanup_request_failed_already_cleaning(  # pylint: disable=unused-argument
        self, sandbox_finished, cleanup_request_started
    ):
        """Test that cleanup fails when a cleanup is already in progress."""
        allocation_unit = sandbox_finished.allocation_unit
        self.assert_cleanup_request_failed(allocation_unit)

    def test_create_cleanup_request_force_already_cleaning(  # pylint: disable=unused-argument
        self, mocker, sandbox_finished, cleanup_request_started
    ):
        """Test that a force cleanup skips when a cleanup is already ongoing."""
        allocation_unit = sandbox_finished.allocation_unit

        def mock_is_finished(_):
            CleanupRequest.is_finished = mocker.PropertyMock()
            CleanupRequest.is_finished.return_value = True

        mocker.patch(
            'crczp.sandbox_instance_app.lib.requests.cancel_cleanup_request',
            side_effect=mock_is_finished,
        )
        self.assert_cleanup_ongoing_force_skipped(allocation_unit)

    def test_create_cleanup_requests(self, sandbox_finished):
        """Test cleanup requests creation for a list of allocation units."""
        allocation_unit = sandbox_finished.allocation_unit

        requests.create_cleanup_requests([allocation_unit])
        self.assert_multiple_cleanup_requests_success([allocation_unit])

    @staticmethod
    def assert_cleanup_request_all_failed(allocation_units: Any) -> None:
        """Assert that cleanup request creation fails for all given allocation units."""
        with pytest.raises(api_exceptions.ValidationError):
            requests.create_cleanup_requests(list(allocation_units))

        for allocation_unit in allocation_units:
            with pytest.raises(ObjectDoesNotExist):
                assert CleanupRequest.objects.get(pk=allocation_unit.id)

    def test_create_cleanup_requests_many_alloc_unfinished_first_fail(self, sandbox_finished):
        """Test that cleanup fails if the first unit has an unfinished allocation."""
        unit_alloc_unfinished = SandboxAllocationUnit.objects.get(pk=1)
        allocation_units = [sandbox_finished.allocation_unit, unit_alloc_unfinished]
        self.assert_cleanup_request_all_failed(allocation_units)

    def test_create_cleanup_requests_many_alloc_unfinished_last_fail(self, sandbox_finished):
        """Test that cleanup fails if the last unit has an unfinished allocation."""
        unit_alloc_unfinished = SandboxAllocationUnit.objects.get(pk=1)
        allocation_units = [unit_alloc_unfinished, sandbox_finished.allocation_unit]
        self.assert_cleanup_request_all_failed(allocation_units)

    def test_create_cleanup_requests_many_alloc_unfinished_locked_force(self, mocker, sandbox_lock):
        """Test that force cleanup succeeds for multiple units including a locked sandbox."""
        mocker.patch(
            'crczp.sandbox_instance_app.lib.requests.request_handlers.AllocationRequestHandler'
        )
        unit_alloc_unfinished = SandboxAllocationUnit.objects.get(pk=1)
        allocation_units = [unit_alloc_unfinished, sandbox_lock.sandbox.allocation_unit]

        requests.create_cleanup_requests(list(allocation_units), True)
        self.assert_multiple_cleanup_requests_success(allocation_units)

    def test_cancel_cleanup_request_success(self, cleanup_request_started):
        """Test that cancellation of a cleanup request delegates to the handler."""
        requests.cancel_cleanup_request(cleanup_request_started)
        self.handler.return_value.cancel_request.assert_called_once_with(cleanup_request_started)

    def test_delete_cleanup_request_success(self, cleanup_request_finished):
        """Test that a finished cleanup request is deleted from the database."""
        requests.delete_cleanup_request(cleanup_request_finished)

        with pytest.raises(ObjectDoesNotExist):
            CleanupRequest.objects.get(pk=cleanup_request_finished.id)

    def test_get_cleanup_request_stages_state(  # pylint: disable=unused-argument
        self, cleanup_request, cleanup_stage_stack, cleanup_stage_networking_started
    ):
        """Test that cleanup stage states are returned in the correct order."""
        stages_state = requests.get_cleanup_request_stages_state(cleanup_request)

        assert stages_state == [
            requests.StageState.IN_QUEUE.value,
            requests.StageState.RUNNING.value,
            requests.StageState.FINISHED.value,
        ]

    def test_get_cleanup_request_stages_state_fail(  # pylint: disable=unused-argument
        self,
        cleanup_request,
        cleanup_stage_stack,
        cleanup_stage_networking_started,
        cleanup_stage_user,
    ):
        """Test that failed cleanup stages are reported as FAILED."""
        cleanup_stage_networking_started.end = timezone.now()
        cleanup_stage_networking_started.failed = True
        cleanup_stage_stack.end = timezone.now()
        cleanup_stage_stack.failed = True

        stages_state = requests.get_cleanup_request_stages_state(cleanup_request)

        assert stages_state == [
            requests.StageState.FAILED.value,
            requests.StageState.FAILED.value,
            requests.StageState.FINISHED.value,
        ]
