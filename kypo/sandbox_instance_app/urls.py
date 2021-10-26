"""Sandbox Instance App urls."""

from django.urls import path

from kypo.sandbox_instance_app import views

urlpatterns = [
    path('pools', views.PoolList.as_view(), name='pool-list'),
    path('pools/<int:pool_id>', views.PoolDetail.as_view(), name='pool-detail'),
    path('pools/<int:pool_id>/definition', views.PoolDefinition.as_view(), name='pool-definition'),
    path('pools/<int:pool_id>/locks', views.PoolLockList.as_view(), name='pool-lock-list'),
    path('pools/<int:pool_id>/locks/<int:lock_id>', views.PoolLockDetail.as_view(),
         name='pool-lock-detail'),
    path('pools/<int:pool_id>/allocation-requests', views.PoolAllocationRequestList.as_view(),
         name='pool-allocation-request-list'),
    path('pools/<int:pool_id>/cleanup-requests', views.PoolCleanupRequests.as_view(),
         name='pool-cleanup-request-list'),

    path('pools/<int:pool_id>/sandbox-allocation-units',
         views.SandboxAllocationUnitList.as_view(), name='sandbox-allocation-unit-list'),

    # Sandbox allocation units
    path('sandbox-allocation-units/<int:unit_id>',
         views.SandboxAllocationUnitDetail.as_view(), name='sandbox-allocation-unit-detail'),
    path('sandbox-allocation-units/<int:unit_id>/allocation-request',
         views.SandboxAllocationRequest.as_view(), name='sandbox-allocation-request'),
    path('sandbox-allocation-units/<int:unit_id>/cleanup-request',
         views.SandboxCleanupRequest.as_view(), name='sandbox-cleanup-request'),

    # Allocation request
    path('allocation-requests/<request_id>',
         views.SandboxAllocationRequestDetail.as_view(), name='sandbox-allocation-request-detail'),
    path('allocation-requests/<int:request_id>/cancel',
         views.SandboxAllocationRequestCancel.as_view(), name='sandbox-allocation-request-cancel'),

    # Cleanup request
    path('cleanup-requests/<int:request_id>',
         views.SandboxCleanupRequestDetail.as_view(), name='sandbox-cleanup-request-detail'),
    path('cleanup-requests/<int:request_id>/cancel',
         views.SandboxCleanupRequestCancel.as_view(), name='sandbox-cleanup-request-cancel'),

    # Stages
    path('allocation-requests/<int:request_id>/stages/openstack',
         views.OpenstackAllocationStageDetail.as_view(),
         name='openstack-allocation-stage'),
    path('cleanup-requests/<int:request_id>/stages/openstack',
         views.OpenstackCleanupStageDetail.as_view(),
         name='openstack-cleanup-stage'),

    path('allocation-requests/<int:request_id>/stages/openstack/events',
         views.SandboxEventList.as_view(), name='stack-events'),
    path('allocation-requests/<int:request_id>/stages/openstack/resources',
         views.SandboxResourceList.as_view(), name='stack-resources'),

    # Pool manipulation
    path('pools/<int:pool_id>/sandboxes', views.PoolSandboxList.as_view(),
         name='pool-sandbox-list'),
    path('pools/<int:pool_id>/sandboxes/get-and-lock', views.SandboxGetAndLock.as_view(),
         name='pool-sandbox-get-and-lock'),
    path('pools/<int:pool_id>/management-ssh-access',
         views.PoolManagementSSHAccess.as_view(),
         name='pool-management-ssh-access'),

    # Sandboxes
    path('sandboxes/<int:sandbox_id>', views.SandboxDetail.as_view(), name='sandbox-detail'),
    path('sandboxes/<int:sandbox_id>/locks', views.SandboxLockList.as_view(),
         name='sandbox-lock-list'),
    path('sandboxes/<int:sandbox_id>/locks/<int:lock_id>', views.SandboxLockDetail.as_view(),
         name='sandbox-lock-detail'),
    path('sandboxes/<int:sandbox_id>/topology',
         views.SandboxTopology.as_view(), name='sandbox-topology'),

    path('sandboxes/<int:sandbox_id>/vms/<str:vm_name>',
         views.SandboxVMDetail.as_view(),  name='sandbox-vm-detail'),
    path('sandboxes/<int:sandbox_id>/vms/<str:vm_name>/console',
         views.SandboxVMConsole.as_view(), name='sandbox-vm-console'),

    path('sandboxes/<int:sandbox_id>/user-ssh-access',
         views.SandboxUserSSHAccess.as_view(),
         name='sandbox-user-ssh-access'),

    path('sandboxes/<int:sandbox_id>/man-out-port-ip',
         views.SandboxManOutPortIP.as_view(),
         name='man-out-port-ip'),
]
