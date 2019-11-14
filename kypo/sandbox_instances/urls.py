from django.urls import path
from django.views.decorators.cache import cache_page

from . import views

WEEK = 3600 * 24 * 7

urlpatterns = [
    path('pools/', views.PoolList.as_view(), name='pool-list'),
    path('pools/<int:pool_id>/', views.PoolDetail.as_view(), name='pool-detail'),

    path('pools/<int:pool_id>/sandbox-allocation-units/',
         views.SandboxAllocationUnitList.as_view(), name='sandbox-allocation-unit-list'),

    # Sandbox allocation units
    path('sandbox-allocation-units/<int:unit_id>/',
         views.SandboxAllocationUnitDetail.as_view(), name='sandbox-allocation-unit-detail'),

    path('sandbox-allocation-units/<int:unit_id>/allocation-requests/<int:request_id>/',
         views.SandboxAllocationRequestDetail.as_view(), name='allocation-request-detail'),
    path('sandbox-allocation-units/<int:unit_id>/allocation-requests/<int:request_id>/stages/',
         views.SandboxCreateRequestStageList.as_view(), name='allocation-request-stage-list'),

    path('sandbox-allocation-units/<int:unit_id>/cleanup-requests/',
         views.SandboxCleanupRequestList.as_view(), name='sandbox-delete-request'),

    path('sandbox-allocation-units/<int:unit_id>/events/',
         views.SandboxEventList.as_view(), name='sandbox-events'),
    path('sandbox-allocation-units/<int:unit_id>/resources/',
         views.SandboxResourceList.as_view(), name='sandbox-resources'),

    # Allocation stages
    path('stages/allocation/<int:stage_id>/openstack/',
         views.OpenstackStageDetail.as_view(), name='openstack-allocation-stage'),

    # Pool manipulation
    path('pools/<int:pool_id>/sandboxes/', views.PoolSandboxList.as_view(),
         name='sandbox-list'),
    path('pools/<int:pool_id>/key-pairs/management/', views.PoolKeypairManagement.as_view(),
         name='pool-mng-key-pair'),

    # Sandboxes
    path('sandboxes/<int:sandbox_id>/', views.SandboxDetail.as_view(), name='sandbox-detail'),
    path('sandboxes/<int:sandbox_id>/lock/', views.SandboxLock.as_view(), name='sandbox-lock'),
    path('sandboxes/<int:sandbox_id>/topology/',
         cache_page(None)(views.SandboxTopology.as_view()), name='sandbox-topology'),

    path('sandboxes/<int:sandbox_id>/key-pairs/user/',
         views.SandboxKeypairUser.as_view(), name='sandbox-user-key-pair'),

    path('sandboxes/<int:sandbox_id>/vms/<str:vm_name>/',
         views.SandboxVMDetail.as_view(),  name='sandbox-vm-detail'),
    path('sandboxes/<int:sandbox_id>/vms/<str:vm_name>/console/',
         views.SandboxVMConsole.as_view(), name='sandbox-vm-console'),

    path('sandboxes/<int:sandbox_id>/user-ssh-config/',
         cache_page(WEEK)(views.SandboxUserSSHConfig.as_view()), name='sandbox-user-ssh-config'),
    path('sandboxes/<int:sandbox_id>/management-ssh-config/',
         cache_page(WEEK)(views.SandboxManagementSSHConfig.as_view()),
         name='sandbox-management-ssh-config'),
]
