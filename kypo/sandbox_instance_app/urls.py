from django.urls import path
from django.views.decorators.cache import cache_page

from kypo.sandbox_instance_app import views

WEEK = 3600 * 24 * 7

urlpatterns = [
    path('pools', views.PoolList.as_view(), name='pool-list'),
    path('pools/<int:pool_id>', views.PoolDetail.as_view(), name='pool-detail'),
    path('pools/<int:pool_id>/definition', views.PoolDefinition.as_view(), name='pool-definition'),
    path('pools/<int:pool_id>/locks', views.PoolLockList.as_view(), name='pool-lock-list'),
    path('pools/<int:pool_id>/locks/<int:lock_id>', views.PoolLockDetail.as_view(),
         name='pool-lock-detail'),
    path('pools/<int:pool_id>/allocation-requests', views.PoolAllocationRequestList.as_view(),
         name='pool-allocation-request-list'),
    path('pools/<int:pool_id>/cleanup-requests', views.PoolCleanupRequestList.as_view(),
         name='pool-cleanup-request-list'),

    path('pools/<int:pool_id>/sandbox-allocation-units',
         views.SandboxAllocationUnitList.as_view(), name='sandbox-allocation-unit-list'),

    # Sandbox allocation units
    path('sandbox-allocation-units/<int:unit_id>',
         views.SandboxAllocationUnitDetail.as_view(), name='sandbox-allocation-unit-detail'),
    # Allocation request
    path('sandbox-allocation-units/<int:unit_id>/allocation-request',
         views.SandboxAllocationRequest.as_view(), name='allocation-request'),
    path('sandbox-allocation-units/<int:unit_id>/allocation-requests/<int:request_id>/cancel',
         views.SandboxAllocationRequestCancel.as_view(), name='allocation-request-cancel/'),
    path('sandbox-allocation-units/<int:unit_id>/allocation-requests/<int:request_id>/stages',
         views.SandboxAllocationRequestStageList.as_view(), name='allocation-request-stage-list'),
    # Cleanup request
    path('sandbox-allocation-units/<int:unit_id>/cleanup-requests',
         views.SandboxCleanupRequestList.as_view(), name='sandbox-cleanup-request-list'),
    path('sandbox-allocation-units/<int:unit_id>/cleanup-requests/<int:request_id>',
         views.SandboxCleanupRequestDetail.as_view(), name='sandbox-cleanup-request-detail'),
    path('sandbox-allocation-units/<int:unit_id>/cleanup-requests/<int:request_id>/stages',
         views.SandboxCleanupRequestStageList.as_view(), name='allocation-request-stage-list'),

    path('sandbox-allocation-units/<int:unit_id>/events',
         views.SandboxEventList.as_view(), name='sandbox-events'),
    path('sandbox-allocation-units/<int:unit_id>/resources',
         views.SandboxResourceList.as_view(), name='sandbox-resources'),

    # Stages
    path('stages/allocation/<int:stage_id>/openstack',
         views.OpenstackAllocationStageDetail.as_view(), name='openstack-allocation-stage'),
    path('stages/cleanup/<int:stage_id>/openstack',
         views.OpenstackCleanupStageDetail.as_view(), name='ansible-cleanup-stage'),

    # Pool manipulation
    path('pools/<int:pool_id>/sandboxes', views.PoolSandboxList.as_view(),
         name='pool-sandbox-list'),
    path('pools/<int:pool_id>/key-pairs/management', views.PoolKeypairManagement.as_view(),
         name='pool-mng-key-pair'),
    path('pools/<int:pool_id>/sandboxes/get-and-lock', views.SandboxGetAndLock.as_view(),
         name='pool-sandbox-get-and-lock'),

    # Sandboxes
    path('sandboxes/<int:sandbox_id>', views.SandboxDetail.as_view(), name='sandbox-detail'),
    path('sandboxes/<int:sandbox_id>/locks', views.SandboxLockList.as_view(),
         name='sandbox-lock-list'),
    path('sandboxes/<int:sandbox_id>/locks/<int:lock_id>', views.SandboxLockDetail.as_view(),
         name='sandbox-lock-detail'),
    path('sandboxes/<int:sandbox_id>/topology',
         cache_page(None)(views.SandboxTopology.as_view()), name='sandbox-topology'),

    path('sandboxes/<int:sandbox_id>/key-pairs/user',
         views.SandboxKeypairUser.as_view(), name='sandbox-user-key-pair'),

    path('sandboxes/<int:sandbox_id>/vms/<str:vm_name>',
         views.SandboxVMDetail.as_view(),  name='sandbox-vm-detail'),
    path('sandboxes/<int:sandbox_id>/vms/<str:vm_name>/console',
         views.SandboxVMConsole.as_view(), name='sandbox-vm-console'),

    path('sandboxes/<int:sandbox_id>/user-ssh-config',
         cache_page(WEEK)(views.SandboxUserSSHConfig.as_view()),
         name='sandbox-user-ssh-config'),
    path('sandboxes/<int:sandbox_id>/management-ssh-config',
         cache_page(WEEK)(views.SandboxManagementSSHConfig.as_view()),
         name='sandbox-management-ssh-config'),
]
