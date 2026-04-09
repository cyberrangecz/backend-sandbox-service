"""Tests for sandbox-allocation-units/by-creator (single-sandbox-per-user Phase 1.2)."""
import pytest
from unittest.mock import patch
from rest_framework.test import APIRequestFactory

from crczp.sandbox_instance_app.models import (
    SandboxAllocationUnit,
    AllocationRequest,
    CleanupRequest,
    StackCleanupStage,
)
from crczp.sandbox_instance_app.views import (
    SandboxAllocationUnitByCreatorListView,
    SandboxAllocationUnitByAgeListView,
    _is_allocation_unit_active,
)


pytestmark = pytest.mark.django_db


class TestSandboxAllocationUnitByCreatorList:
    """Per-user active listing endpoint."""

    @pytest.fixture
    def unit_a1(self, pool):
        return SandboxAllocationUnit.objects.create(
            pool=pool,
            created_by_sub='user-a',
        )

    @pytest.fixture
    def unit_a2(self, pool):
        return SandboxAllocationUnit.objects.create(
            pool=pool,
            created_by_sub='user-a',
        )

    @pytest.fixture
    def unit_b1(self, pool):
        return SandboxAllocationUnit.objects.create(
            pool=pool,
            created_by_sub='user-b',
        )

    @pytest.fixture
    def factory(self):
        return APIRequestFactory()

    def test_list_by_creator_returns_only_that_creator(
        self, pool, unit_a1, unit_a2, unit_b1, factory
    ):
        """Call with created_by_sub=user-a returns only user-a's units."""
        with patch.object(
            SandboxAllocationUnitByCreatorListView,
            'permission_classes',
            [],
        ):
            request = factory.get(
                '/sandbox-allocation-units/by-creator/',
                {'created_by_sub': 'user-a'},
            )
            view = SandboxAllocationUnitByCreatorListView.as_view()
            response = view(request)
        assert response.status_code == 200
        data = response.data
        if hasattr(data, 'get') and 'results' in data:
            ids = [x['id'] for x in data['results']]
        else:
            ids = [x['id'] for x in data]
        assert set(ids) == {unit_a1.id, unit_a2.id}
        assert unit_b1.id not in ids

    def test_list_with_state_active_excludes_finished_cleanup(
        self, pool, unit_a1, factory
    ):
        """When state=ACTIVE, units with finished cleanup are excluded."""
        AllocationRequest.objects.create(allocation_unit=unit_a1)
        cleanup = CleanupRequest.objects.create(allocation_unit=unit_a1)
        StackCleanupStage.objects.create(
            cleanup_request=cleanup,
            cleanup_request_fk_many=cleanup,
            finished=True,
        )
        with patch.object(
            SandboxAllocationUnitByCreatorListView,
            'permission_classes',
            [],
        ):
            request = factory.get(
                '/sandbox-allocation-units/by-creator/',
                {'created_by_sub': 'user-a', 'state': 'ACTIVE'},
            )
            view = SandboxAllocationUnitByCreatorListView.as_view()
            response = view(request)
        assert response.status_code == 200
        data = response.data
        # View uses pagination_class = None, so response is a list
        items = data if isinstance(data, list) else (data.get('results') or [])
        ids = [x['id'] for x in items]
        # Unit with finished cleanup should not be in ACTIVE list
        assert unit_a1.id not in ids


class TestSandboxAllocationUnitByAgeList:
    """Age-based listing for cleanup job (Phase 1.3)."""

    @pytest.fixture
    def factory(self):
        return APIRequestFactory()

    def test_list_by_age_returns_only_older_units(
        self, pool, factory
    ):
        """created_before filters to units with created_at < timestamp."""
        from django.utils import timezone
        from datetime import timedelta
        old = timezone.now() - timedelta(hours=25)
        new = timezone.now() - timedelta(hours=1)
        u_old = SandboxAllocationUnit.objects.create(
            pool=pool,
            created_by_sub='user-x',
        )
        u_old.created_at = old
        u_old.save(update_fields=['created_at'])
        u_new = SandboxAllocationUnit.objects.create(
            pool=pool,
            created_by_sub='user-x',
        )
        u_new.created_at = new
        u_new.save(update_fields=['created_at'])
        cutoff = (old + timedelta(hours=24)).isoformat()
        with patch.object(
            SandboxAllocationUnitByAgeListView,
            'permission_classes',
            [],
        ):
            request = factory.get(
                '/sandbox-allocation-units/by-age/',
                {'created_before': cutoff},
            )
            view = SandboxAllocationUnitByAgeListView.as_view()
            response = view(request)
        assert response.status_code == 200
        data = response.data
        ids = [x['id'] for x in (data.get('results') or data)]
        assert u_old.id in ids
        assert u_new.id not in ids
        # Response must include created_by_sub for cleanup job
        for item in (data.get('results') or data):
            if item['id'] == u_old.id:
                assert item.get('created_by_sub') == 'user-x'
                break


class TestIsAllocationUnitActive:
    """Helper _is_allocation_unit_active."""

    def test_unit_without_cleanup_is_active(self, pool, allocation_unit):
        """Unit with no cleanup request is active."""
        allocation_unit.created_by_sub = 'sub'
        allocation_unit.save()
        assert _is_allocation_unit_active(allocation_unit) is True
