import pytest
from rest_framework.reverse import reverse
from rest_framework.test import APIRequestFactory

from kypo.sandbox_ansible_app.views import NetworkingAnsibleAllocationStageDetailView

pytestmark = pytest.mark.django_db

ALLOCATION_REQUEST_ID = 1


class TestStages:

    @pytest.fixture
    def arf(self):
        return APIRequestFactory()

    def test_networking_stage_views(self, arf):
        request_kwargs = {'request_id': ALLOCATION_REQUEST_ID}
        request = arf.get(reverse('networking-ansible-allocation-stage', kwargs=request_kwargs))
        response = NetworkingAnsibleAllocationStageDetailView.as_view()(request, request_id=ALLOCATION_REQUEST_ID)

        assert response.data['id'] == 2
        assert response.data['rev'] == '04e97bb05456b37a74cd28732547b65f213e1b99'
        assert response.data['request_id'] == 1
